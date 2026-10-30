"""Long-term memory with provenance, dependency tracking and revocation.

Every memory item keeps where it came from, what authority it carries, how far
it applies and which items were derived from it. Revocation walks the
dependency graph, which is the primitive the recovery experiments need.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

from .schema import Authority, Event, Kind, Lifetime, Transform, Verification, now_iso
from .store import EventStore

RETRIEVER_VERSION = "retriever.v1"

MEM_TYPES = ("fact", "procedure", "preference", "constraint", "authority")


@dataclass
class MemoryItem:
    id: str
    content: str
    mtype: str = "fact"
    source_id: str = "unknown"
    authority: str = Authority.MODEL_INFERENCE
    scope: dict = field(default_factory=dict)
    lifetime: str = Lifetime.SESSION
    version: int = 1
    parents: list[str] = field(default_factory=list)
    verification_status: str = Verification.UNVERIFIED
    created_at: str = field(default_factory=now_iso)
    superseded_by: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _terms(text: str) -> set[str]:
    text = text.lower()
    toks = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2}", text)
    return set(toks)


class MemoryStore:
    def __init__(self, store: EventStore, task_id: str, session_id: str):
        self.store = store
        self.task_id = task_id
        self.session_id = session_id
        self.items: dict[str, MemoryItem] = {}

    # -- write / read ----------------------------------------------------
    def write(
        self,
        content: str,
        mtype: str = "fact",
        source_id: str = "agent",
        authority: str = Authority.MODEL_INFERENCE,
        parents: Optional[list[str]] = None,
        scope: Optional[dict] = None,
        lifetime: str = Lifetime.SESSION,
        verification_status: str = Verification.UNVERIFIED,
    ) -> MemoryItem:
        if mtype not in MEM_TYPES:
            raise ValueError("unknown memory type: %s" % mtype)
        item = MemoryItem(
            id="mem_%s" % uuid.uuid4().hex[:10],
            content=content,
            mtype=mtype,
            source_id=source_id,
            authority=authority,
            parents=list(parents or []),
            scope=dict(scope or {}),
            lifetime=lifetime,
            verification_status=verification_status,
        )
        self.items[item.id] = item
        self.store.append(
            Event(
                kind=Kind.MEMORY_WRITE,
                task_id=self.task_id,
                session_id=self.session_id,
                obj_id=item.id,
                source_id=source_id,
                version=item.version,
                parents=item.parents,
                authority=authority,
                scope=item.scope,
                lifetime=lifetime,
                transformation=Transform.DERIVE_MEMORY,
                content=content,
                verification_status=verification_status,
                retriever_version=RETRIEVER_VERSION,
                extra={"mtype": mtype},
            )
        )
        return item

    def retrieve(self, query: str, k: int = 5) -> list[MemoryItem]:
        q = _terms(query)
        scored = []
        for item in self.items.values():
            if item.superseded_by or item.verification_status == Verification.REVOKED:
                continue
            overlap = len(q & _terms(item.content))
            if overlap:
                scored.append((overlap, item))
        scored.sort(key=lambda x: -x[0])
        top = [i for _, i in scored[:k]]
        self.store.append(
            Event(
                kind=Kind.MEMORY_RETRIEVE,
                task_id=self.task_id,
                session_id=self.session_id,
                authority=Authority.MODEL_INFERENCE,
                transformation=Transform.RETRIEVE,
                content=query,
                retriever_version=RETRIEVER_VERSION,
                extra={"returned": [i.id for i in top]},
            )
        )
        return top

    # -- revision --------------------------------------------------------
    def supersede(self, item_id: str, new_content: str, source_id: str = "agent") -> Optional[MemoryItem]:
        old = self.items.get(item_id)
        if old is None:
            return None
        new = self.write(
            new_content,
            mtype=old.mtype,
            source_id=source_id,
            authority=old.authority,
            parents=[item_id],
            scope=old.scope,
            lifetime=old.lifetime,
        )
        old.superseded_by = new.id
        new.version = old.version + 1
        return new

    def revoke(self, item_id: str, reason: str = "source withdrawn") -> list[str]:
        """Revoke an item and mark every descendant stale. Returns affected ids."""
        if item_id not in self.items:
            return []
        affected = [item_id] + self.descendants(item_id)
        for aid in affected:
            item = self.items[aid]
            item.verification_status = Verification.STALE if aid != item_id else Verification.REVOKED
        self.store.append(
            Event(
                kind=Kind.REVOKE,
                task_id=self.task_id,
                session_id=self.session_id,
                obj_id=item_id,
                authority=Authority.SYSTEM_RULE,
                transformation=Transform.REVOKE,
                verification_status=Verification.REVOKED,
                content=reason,
                extra={"affected": affected, "reason": reason},
            )
        )
        return affected

    def descendants(self, item_id: str) -> list[str]:
        out, frontier = [], [item_id]
        while frontier:
            cur = frontier.pop()
            for item in self.items.values():
                if cur in item.parents and item.id not in out:
                    out.append(item.id)
                    frontier.append(item.id)
        return out

    def repair(self, item_id: str, corrected: str, evidence: str = "") -> Optional[MemoryItem]:
        old = self.items.get(item_id)
        if old is None:
            return None
        new = self.write(
            corrected,
            mtype=old.mtype,
            source_id=evidence or old.source_id,
            authority=Authority.SYSTEM_RULE,
            parents=[item_id],
            scope=old.scope,
            verification_status=Verification.VERIFIED,
        )
        old.superseded_by = new.id
        self.store.append(
            Event(
                kind=Kind.REPAIR,
                task_id=self.task_id,
                session_id=self.session_id,
                obj_id=item_id,
                parents=[item_id],
                transformation=Transform.REPAIR,
                content=corrected,
                verification_status=Verification.VERIFIED,
                extra={"new_id": new.id},
            )
        )
        return new

    # -- diagnostics -----------------------------------------------------
    def poisoned_fraction(self, source_prefix: str = "poison") -> float:
        if not self.items:
            return 0.0
        bad = [i for i in self.items.values() if i.source_id.startswith(source_prefix) and not i.superseded_by]
        return len(bad) / len(self.items)

    def snapshot(self) -> list[dict]:
        return [i.to_dict() for i in self.items.values()]
