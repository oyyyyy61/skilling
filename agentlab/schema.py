"""Event / state schema for the long-running agent state-safety lab.

Implements the provenance tuple required by section 5 of the research plan.
Every state change -- a rule ingested, a memory derived, a context compacted,
a skill loaded, a tool executed, a source revoked -- becomes one Event that
carries where it came from, who was allowed to act on it, how far it reaches,
how long it lives, what produced it, and what evidence supports it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

STATE_SCHEMA = "agentlab.state.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


class Authority:
    """Where a state object's action authority comes from.

    Only rules and explicit user instructions may drive consequential tool
    actions. Tool output, documents, skill text and model inference carry
    content but not action authority. This separation is what makes the
    "rule was remembered" vs "rule still binds action" distinction testable.
    """

    SYSTEM_RULE = "system_rule"
    USER_INSTRUCTION = "user_instruction"
    TOOL_OUTPUT = "tool_output"
    DOCUMENT = "document"
    SKILL_TEXT = "skill_text"
    MEMORY_DERIVED = "memory_derived"
    MODEL_INFERENCE = "model_inference"


# Authorities that are allowed to authorise a consequential action.
ACTION_AUTHORITIES = frozenset({Authority.SYSTEM_RULE, Authority.USER_INSTRUCTION})


class Lifetime:
    TURN = "turn"
    SESSION = "session"
    PERSISTENT = "persistent"


class Verification:
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REVOKED = "revoked"
    CONFLICT = "conflict"
    STALE = "stale"


class Transform:
    """The operation that produced a state object."""

    INGEST = "ingest"
    SUMMARIZE = "summarize"
    DERIVE_MEMORY = "derive_memory"
    DERIVE_SKILL = "derive_skill"
    RETRIEVE = "retrieve"
    COMPOSE = "compose"
    MIGRATE = "migrate"
    REVOKE = "revoke"
    REPAIR = "repair"
    POLLUTE = "pollute"
    TRUNCATE = "truncate"


class Kind:
    """Event kinds recorded in the trace."""

    TASK_START = "task_start"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    MEMORY_WRITE = "memory_write"
    MEMORY_RETRIEVE = "memory_retrieve"
    SKILL_LOAD = "skill_load"
    COMPACTION = "compaction"
    POLLUTION = "pollution"
    REVOKE = "revoke"
    REPAIR = "repair"
    PROBE = "probe"
    TASK_END = "task_end"


@dataclass
class Event:
    """One recorded state transition.

    Field names deliberately mirror section 5 of the research plan so that a
    trace can be read against the plan without translation.
    """

    kind: str
    task_id: str
    session_id: str
    # identity of the state object this event concerns (memory / skill / rule)
    obj_id: Optional[str] = None
    source_id: Optional[str] = None
    version: Optional[int] = None
    parents: list[str] = field(default_factory=list)
    authority: str = Authority.MODEL_INFERENCE
    scope: dict = field(default_factory=dict)
    lifetime: str = Lifetime.SESSION
    transformation: Optional[str] = None
    evidence: dict = field(default_factory=dict)
    evidence_hash: Optional[str] = None
    uncertainty: Optional[float] = None
    verification_status: str = Verification.UNVERIFIED
    authorization: str = "n/a"
    # runtime / component versions
    state_schema: str = STATE_SCHEMA
    policy_version: str = "policy.v1"
    model_version: Optional[str] = None
    retriever_version: Optional[str] = None
    tool_version: Optional[str] = None
    model_snapshot: Optional[str] = None
    prompt_hash: Optional[str] = None
    # payloads
    content: Optional[str] = None
    tool_call: Optional[dict] = None
    effect: Optional[dict] = None
    extra: dict = field(default_factory=dict)
    # bookkeeping
    event_id: str = field(default_factory=lambda: new_id("ev"))
    ts: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def canonical(self) -> str:
        """Stable serialisation used for hashing and diffing."""
        d = self.to_dict()
        for drop in ("event_id", "ts"):
            d.pop(drop, None)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)


@dataclass
class Rule:
    """A rule that constrains tool action.

    Rules are first-class state objects: they have a source, an authority, a
    declared scope, a lifetime and a version, so that loss of scope or
    authority can be measured separately from loss of wording.
    """

    id: str
    text: str
    kind: str  # resource | tool | network | approval | deadline | skill
    params: dict = field(default_factory=dict)
    authority: str = Authority.SYSTEM_RULE
    scope: dict = field(default_factory=dict)
    lifetime: str = Lifetime.SESSION
    version: int = 1
    status: str = "active"  # active | superseded | revoked | expired
    source_id: str = "system_prompt"
    parents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def restated(self) -> str:
        """The verbatim text the protected-rule channel re-injects."""
        return "[%s] %s" % (self.id, self.text)


@dataclass
class Decision:
    """Tool-broker verdict for one tool call."""

    allow: bool
    reason: str = ""
    rule_id: Optional[str] = None
    needs_approval: bool = False
    violation: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
