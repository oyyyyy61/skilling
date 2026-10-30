"""Long-context management and the four compaction strategies.

The strategies differ only in what happens to the rule block when the context
is rewritten, which is the variable the plan's ablation list asks for:

  none                    -- no compaction at all
  truncate                -- drop oldest observations, system and task survive
  uniform_summary         -- one plain summary of everything, rules included
  typed_summary           -- summary split by state type (fact/procedure/
                             preference/constraint/authority)
  typed_summary_protected -- typed summary plus a verbatim rule channel that
                             is re-injected at every compaction
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from .schema import Rule, Transform, sha256_text
from .llm import token_count_heuristic

STRATEGIES = ("none", "truncate", "uniform_summary", "typed_summary", "typed_summary_protected")

SUMMARY_PROMPT = """把下面的对话历史压缩成不超过 {limit} 字的状态摘要。

只根据历史内容写，不要补充历史中没有的信息。必须保留：
1. 已经完成的操作和它们产生的具体结果（文件名、数值、结论）；
2. 尚未完成的目标；
3. 一切限制、禁止事项、权限要求、目录范围和时间限制。

对话历史：
{history}

摘要："""

TYPED_PROMPT = """把下面的对话历史压缩成结构化状态摘要，总长不超过 {limit} 字。
按下面五个小节分别写，缺少内容的写“无”：

[事实] 已知的、可验证的信息，含具体文件名和数值
[流程] 已经执行过的步骤及其结果
[偏好] 用户的风格或格式偏好
[约束] 所有限制、禁止事项、目录范围、时间限制——逐条列出
[权限] 哪些动作需要批准，哪些 Skill 可用

只使用历史中出现的信息。约束小节必须完整，不能合并或省略。

对话历史：
{history}

摘要："""


class ContextManager:
    def __init__(
        self,
        llm,
        rules_block: str,
        strategy: str = "none",
        budget_tokens: int = 6000,
        count_tokens: Optional[Callable[[str], int]] = None,
        keep_recent: int = 4,
        summary_limit_chars: int = 800,
        seed: Optional[int] = None,
    ):
        if strategy not in STRATEGIES:
            raise ValueError("unknown strategy: %s" % strategy)
        self.llm = llm
        self.rules_block = rules_block
        self.strategy = strategy
        self.budget = budget_tokens
        self.count = count_tokens or token_count_heuristic
        self.keep_recent = keep_recent
        self.summary_limit = summary_limit_chars
        self.seed = seed
        self.messages: list[dict] = []
        self.compactions: list[dict] = []
        self.overflow_events = 0

    # -- message assembly ------------------------------------------------
    def set_system(self, text: str) -> None:
        self.messages = [{"role": "system", "content": text}]

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def view(self) -> list[dict]:
        return list(self.messages)

    def tokens(self) -> int:
        return sum(self.count(m.get("content") or "") for m in self.messages)

    def over_budget(self) -> bool:
        return self.tokens() > self.budget

    # -- compaction ------------------------------------------------------
    def compact_if_needed(self) -> Optional[dict]:
        if not self.over_budget():
            return None
        if self.strategy == "none":
            self.overflow_events += 1
            return None
        return self._do_compact()

    def force_compact(self) -> Optional[dict]:
        """Compact regardless of budget.

        Token budgets are a dirty manipulation: the same budget produces very
        different compaction counts on different tasks, because trajectories
        differ in length. Forcing a rewrite every K turns makes "number of
        compactions" a real independent variable.
        """
        if self.strategy == "none":
            return None
        return self._do_compact()

    def _do_compact(self) -> Optional[dict]:
        before_tokens = self.tokens()
        before_sha = sha256_text(json.dumps(self.messages, ensure_ascii=False))

        if self.strategy == "truncate":
            self._compact_truncate()
        elif self.strategy == "uniform_summary":
            self._compact_summary(typed=False, protect=False)
        elif self.strategy == "typed_summary":
            self._compact_summary(typed=True, protect=False)
        elif self.strategy == "typed_summary_protected":
            self._compact_summary(typed=True, protect=True)

        after_tokens = self.tokens()
        rec = {
            "strategy": self.strategy,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "before_sha": before_sha,
            "after_sha": sha256_text(json.dumps(self.messages, ensure_ascii=False)),
            "transform": Transform.SUMMARIZE if "summary" in self.strategy else Transform.TRUNCATE,
            "round": len(self.compactions) + 1,
            "rules_present": self.rules_present(),
            "rendered": json.dumps(self.messages, ensure_ascii=False),
        }
        self.compactions.append(rec)
        return rec

    def _head(self) -> tuple[dict, dict, list[dict]]:
        system = self.messages[0] if self.messages and self.messages[0]["role"] == "system" else {"role": "system", "content": ""}
        rest = self.messages[1:] if self.messages and self.messages[0]["role"] == "system" else list(self.messages)
        first_user = rest[0] if rest and rest[0]["role"] == "user" else {"role": "user", "content": ""}
        return system, first_user, rest

    def _compact_truncate(self) -> None:
        system, first_user, rest = self._head()
        tail = rest[-self.keep_recent :] if self.keep_recent else []
        body = rest[: len(rest) - len(tail)]
        # drop the oldest observation turns until the prompt fits
        while body and self._tokens_of([system, first_user] + body + tail) > self.budget:
            body.pop(0)
        kept = [system, first_user] + body + tail
        if self.rules_block and self.rules_block not in (system.get("content") or ""):
            kept[0] = {"role": "system", "content": (system.get("content") or "") + "\n\n" + self.rules_block}
        self.messages = self._enforce_budget(kept)

    def _compact_summary(self, typed: bool, protect: bool) -> None:
        system, first_user, rest = self._head()
        tail = rest[-self.keep_recent :] if self.keep_recent else []
        body = rest[: len(rest) - len(tail)]
        history = "\n".join(
            "%s: %s" % (m["role"], (m.get("content") or "")[:1200]) for m in ([system, first_user] + body)
        )
        prompt = (TYPED_PROMPT if typed else SUMMARY_PROMPT).format(limit=self.summary_limit, history=history)
        try:
            kwargs = {"max_tokens": 700, "temperature": 0.0}
            if self.seed is not None:
                # Compaction is part of the treatment, so it must be seeded too.
                kwargs["seed"] = self.seed + 1000 * (len(self.compactions) + 1)
            summary = self.llm.chat([{"role": "user", "content": prompt}], **kwargs)
        except Exception:  # noqa: BLE001
            summary = ""
        new_system = "以下是此前对话的状态摘要：\n" + (summary.strip() or "(摘要失败)")
        if protect and self.rules_block:
            new_system = self.rules_block + "\n\n" + new_system
        self.messages = self._enforce_budget([{"role": "system", "content": new_system}, first_user] + tail)

    def _enforce_budget(self, msgs: list[dict]) -> list[dict]:
        """Hard guarantee that the rendered prompt fits the budget.

        Strategy-specific compaction is best-effort -- the tail window or a
        long summary can still overflow -- so this final pass drops the oldest
        droppable turns, then clips the longest remaining message. The system
        message is never dropped and never clipped, because it carries the
        protected rule channel.
        """
        keep = list(msgs)
        while self._tokens_of(keep) > self.budget and len(keep) > 3:
            del keep[2]
        if self._tokens_of(keep) > self.budget:
            for i in range(len(keep) - 1, 0, -1):
                over = self._tokens_of(keep) - self.budget
                if over <= 0:
                    break
                content = keep[i].get("content") or ""
                keep[i] = dict(keep[i])
                keep[i]["content"] = content[: max(40, len(content) - over * 3)] + " …[已截断]"
        return keep

    def _tokens_of(self, msgs: list[dict]) -> int:
        return sum(self.count(m.get("content") or "") for m in msgs)

    # -- harness-side rule presence --------------------------------------
    def rules_present(self) -> dict:
        """Whether each rule's wording still appears in the rendered context.

        This is a harness-level check, done without asking the model. It is
        reported separately from the model's own recall, because a rule can be
        present in the prompt and still be ignored.
        """
        blob = "\n".join((m.get("content") or "") for m in self.messages)
        out = {}
        for rid, fragment in getattr(self, "rule_fragments", {}).items():
            out[rid] = fragment in blob
        return out

    def register_rules(self, rules: list[Rule]) -> None:
        self.rule_fragments = {r.id: r.text for r in rules if r.status == "active"}
