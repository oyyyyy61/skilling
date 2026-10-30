"""Append-only event store, deterministic replay and trace diffing.

The store keeps one JSONL event log plus a content-addressed blob directory,
so that any recorded state object can be re-read byte-for-byte later. Replay
reconstructs the state timeline without calling the model, which is what makes
"same task, same trace, explainable tool effect" checkable.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter, defaultdict
from typing import Iterable, Optional

from .schema import Event, Kind, Rule, Verification, sha256_text


class EventStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.events_path = os.path.join(self.root, "events.jsonl")
        self.blob_dir = os.path.join(self.root, "blobs")
        os.makedirs(self.blob_dir, exist_ok=True)
        if not os.path.exists(self.events_path):
            open(self.events_path, "w", encoding="utf-8").close()

    # -- writing ---------------------------------------------------------
    def put_blob(self, text: str) -> str:
        h = sha256_text(text)
        path = os.path.join(self.blob_dir, h)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return h

    def get_blob(self, h: str) -> str:
        with open(os.path.join(self.blob_dir, h), encoding="utf-8") as f:
            return f.read()

    def append(self, ev: Event) -> Event:
        if ev.content is not None and ev.evidence_hash is None:
            ev.evidence_hash = self.put_blob(ev.content)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        return ev

    def extend(self, events: Iterable[Event]) -> None:
        for ev in events:
            self.append(ev)

    # -- reading ---------------------------------------------------------
    def load(self, task_id: Optional[str] = None, session_id: Optional[str] = None) -> list[Event]:
        out = []
        with open(self.events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = Event.from_dict(json.loads(line))
                if task_id and ev.task_id != task_id:
                    continue
                if session_id and ev.session_id != session_id:
                    continue
                out.append(ev)
        return out

    def sessions(self) -> list[str]:
        seen = []
        for ev in self.load():
            if ev.session_id not in seen:
                seen.append(ev.session_id)
        return seen

    # -- replay ----------------------------------------------------------
    def replay(self, session_id: str) -> "Trace":
        return Trace(session_id, self.load(session_id=session_id), self)

    def diff(self, session_a: str, session_b: str) -> dict:
        a = [e.canonical() for e in self.load(session_id=session_a) if e.kind != Kind.MODEL_CALL]
        b = [e.canonical() for e in self.load(session_id=session_b) if e.kind != Kind.MODEL_CALL]
        first = None
        for i in range(min(len(a), len(b))):
            if a[i] != b[i]:
                first = i
                break
        if first is None and len(a) != len(b):
            first = min(len(a), len(b))
        return {
            "a_len": len(a),
            "b_len": len(b),
            "identical": first is None and len(a) == len(b),
            "first_divergence": first,
        }


class Trace:
    """Read-side view over one session's events."""

    def __init__(self, session_id: str, events: list[Event], store: EventStore):
        self.session_id = session_id
        self.events = events
        self.store = store

    def __len__(self) -> int:
        return len(self.events)

    def of_kind(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    @property
    def tool_calls(self) -> list[Event]:
        return self.of_kind(Kind.TOOL_CALL)

    @property
    def compactions(self) -> list[Event]:
        return self.of_kind(Kind.COMPACTION)

    @property
    def violations(self) -> list[Event]:
        return [e for e in self.tool_calls if (e.effect or {}).get("violation")]

    @property
    def blocked_actions(self) -> list[Event]:
        return [e for e in self.tool_calls if e.authorization == "denied"]

    @property
    def effects(self) -> list[dict]:
        return [e.effect for e in self.tool_calls if e.effect]

    def rules_timeline(self) -> list[dict]:
        """Rule state after each event, for plotting retention over turns."""
        state: dict[str, dict] = {}
        timeline = []
        for ev in self.events:
            if ev.kind in (Kind.TASK_START, Kind.REVOKE, Kind.REPAIR) and ev.extra.get("rules"):
                for r in ev.extra["rules"]:
                    state[r["id"]] = dict(r)
            for rid in (ev.extra.get("rules_revoked") or []):
                if rid in state:
                    state[rid]["status"] = "revoked"
            timeline.append({"t": ev.ts, "kind": ev.kind, "rules": [dict(v) for v in state.values()]})
        return timeline

    def summary(self) -> dict:
        kinds = Counter(e.kind for e in self.events)
        return {
            "session_id": self.session_id,
            "events": len(self.events),
            "kinds": dict(kinds),
            "tool_calls": len(self.tool_calls),
            "violations": len(self.violations),
            "blocked": len(self.blocked_actions),
            "compactions": len(self.compactions),
            "distinct_tools": sorted({(e.tool_call or {}).get("name") for e in self.tool_calls}),
        }

    def effect_log(self) -> list[str]:
        """Human-readable, ordered list of resource-level effects."""
        lines = []
        for e in self.tool_calls:
            eff = e.effect or {}
            call = e.tool_call or {}
            name = call.get("name", "?")
            args = call.get("args", {})
            if eff.get("blocked"):
                lines.append("BLOCKED  %-12s %s  (%s)" % (name, args.get("path") or args.get("sql") or args.get("url") or "", eff.get("reason", "")))
            elif eff.get("error"):
                lines.append("ERROR    %-12s %s  (%s)" % (name, args.get("path") or "", eff.get("error")))
            elif name.startswith("fs_"):
                lines.append("OK       %-12s %s" % (name, eff.get("path")))
            elif name.startswith("db_"):
                lines.append("OK       %-12s %s" % (name, str(eff.get("sql"))[:70]))
            else:
                lines.append("OK       %-12s %s" % (name, eff.get("url") or ""))
        return lines


def verify_determinism(store: EventStore, session_id: str) -> dict:
    """Check that replaying a session is stable (pure read-side operation)."""
    t1 = store.replay(session_id)
    t2 = store.replay(session_id)
    same = [e.canonical() for e in t1.events] == [e.canonical() for e in t2.events]
    return {"session_id": session_id, "deterministic": same, "events": len(t1)}
