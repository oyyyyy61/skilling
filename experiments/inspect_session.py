"""Inspect one session: ordered events, tool calls and effects (replay demo)."""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: inspect_session.py <store_dir> <session_prefix> [n]")
        return 2
    store = EventStore(sys.argv[1])
    prefix = sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 40

    sessions = [s for s in store.sessions() if s.startswith(prefix)]
    if not sessions:
        print("no session matching %r" % prefix)
        print("available:", store.sessions()[:10])
        return 1
    sid = sessions[0]
    trace = store.replay(sid)
    print("session:", sid)
    print("summary:", trace.summary())
    print()
    for ev in trace.events[:n]:
        if ev.kind == "model_call":
            content = (ev.content or "").replace("\n", " ")[:150]
            print("  MODEL      %s" % content)
        elif ev.kind == "tool_call":
            call = ev.tool_call or {}
            print("  TOOL       %-10s %s -> %s" % (call.get("name"), str(call.get("args"))[:70], ev.authorization))
        elif ev.kind == "task_end":
            print("  END        %s" % (ev.content or "")[:200])
        elif ev.kind == "compaction":
            e = ev.extra or {}
            print("  COMPACT    %s %s->%s tokens" % (e.get("strategy"), e.get("before_tokens"), e.get("after_tokens")))
        else:
            print("  %-10s %s" % (ev.kind.upper(), (ev.content or "")[:120].replace("\n", " ")))
    print()
    print("effects:")
    for line in trace.effect_log()[:n]:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
