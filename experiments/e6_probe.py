"""看某类 session 的实际工具调用，核对 classify_effect 判得对不对"""

from __future__ import annotations

import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402
from agentlab.pollute import classify_effect  # noqa: E402

SESS_RE = re.compile(r"^sess_(?P<task>[^_]+)_[^_]+_[^_]+_(?P<tag>.*)$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--task", default="B3")
    ap.add_argument("--limit", type=int, default=2)
    args = ap.parse_args()

    store = EventStore(args.store)
    picked = 0
    for sid in store.sessions():
        m = SESS_RE.match(sid)
        if not m or m.group("task") != args.task:
            continue
        picked += 1
        print("\n=== %s" % sid)
        for tc in store.replay(sid).tool_calls[:12]:
            eff = tc.effect or {}
            print("  tool=%-10s effect=%-55s -> %s"
                  % (str(getattr(tc, "tool", "?")), str(eff), classify_effect(eff)))
        if picked >= args.limit:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
