"""Chat client for the local vLLM server, plus a scripted mock for tests."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional


class LLMError(RuntimeError):
    pass


class LLMClient:
    """OpenAI-compatible client pointed at the local vLLM server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "qwen2.5-7b",
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout: int = 180,
        retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries
        self.calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if seed is not None:
            # vLLM honours this per request; identical seed + identical prompt
            # is the only way to tell "strategy effect" from "sampling noise".
            body["seed"] = int(seed)
        data = json.dumps(body).encode("utf-8")
        last = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    self.base_url + "/chat/completions",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.load(resp)
                usage = payload.get("usage") or {}
                self.calls += 1
                self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                self.total_completion_tokens += usage.get("completion_tokens", 0)
                return payload["choices"][0]["message"]["content"] or ""
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError("LLM call failed: %s" % last)

    def stats(self) -> dict:
        return {
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
        }


class MockLLM:
    """Deterministic stand-in used by unit tests (no GPU needed)."""

    def __init__(self, script: Optional[list[str]] = None, default: str = '{"tool":"fs_list","args":{"path":""}}'):
        self.script = list(script or [])
        self.default = default
        self.calls = 0
        self.prompts: list[list[dict]] = []

    def chat(self, messages: list[dict], **kwargs) -> str:
        self.calls += 1
        self.prompts.append(messages)
        if self.script:
            return self.script.pop(0)
        return self.default

    def stats(self) -> dict:
        return {"model": "mock", "calls": self.calls, "prompt_tokens": 0, "completion_tokens": 0}


def token_count_heuristic(text: str) -> int:
    """Cheap token estimate when no tokenizer is wired in.

    Chinese text runs roughly one token per 1.5 characters; ASCII about one
    per four. Good enough to keep the tests GPU-free, never used as a metric.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


class TokenizerCounter:
    """Real tokenizer counting, with a heuristic fallback.

    Budget decisions must use the same tokenizer the model uses, otherwise the
    "800 token" and "8K token" conditions are not comparable across runs.
    """

    def __init__(self, path: Optional[str] = None, model: Optional[str] = None):
        self.tok = None
        self.source = "heuristic"
        try:
            from transformers import AutoTokenizer  # local import: optional dep

            self.tok = AutoTokenizer.from_pretrained(path or model, trust_remote_code=True)
            self.source = "tokenizer:%s" % (path or model)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)

    def count_text(self, text: str) -> int:
        if self.tok is None:
            return token_count_heuristic(text)
        return len(self.tok.encode(text, add_special_tokens=False))

    def count_messages(self, messages: list[dict]) -> int:
        """Tokens the model will actually condition on, chat template included."""
        if self.tok is None:
            return sum(token_count_heuristic(m.get("content") or "") for m in messages)
        try:
            out = self.tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
            # transformers returns a BatchEncoding (a dict of input_ids /
            # attention_mask). len() on it counts *keys*, so the old code
            # reported 2 tokens for every prompt. Unwrap before measuring.
            if isinstance(out, dict) or hasattr(out, "keys"):
                out = out["input_ids"]
            if isinstance(out, (list, tuple)) and out and isinstance(out[0], (list, tuple)):
                out = out[0]
            n = len(out)
            if n <= 1:
                raise ValueError("degenerate chat template output")
            return n
        except Exception:  # noqa: BLE001
            return sum(self.count_text(m.get("content") or "") for m in messages)
