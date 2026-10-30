"""E7 的稳健性检查：按"每次工具调用"而不是"每个 episode"归一化。

压缩会改变轨迹长度（受保护条件平均 2.6 次压缩、轮次更多），于是"每个 episode
越界一次"这个口径把机会数不同当成了风险不同。这里从事件库直接数工具调用，
给出每次调用的越界率。
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402
from agentlab.pollute import classify_effect  # noqa: E402

HARM_KINDS = ("secret_exposure", "out_of_scope_write", "db_mutation", "network_access")
JSONL = "/root/autodl-tmp/work/lab/results/e7_e7_v2.jsonl"
STORE = "/root/autodl-tmp/work/lab/results/store_e7_v2"


def main() -> int:
    rows = [json.loads(l) for l in open(JSONL, encoding="utf-8") if l.strip()]
    store = EventStore(STORE)

    agg = defaultdict(lambda: {"eps": 0, "eps_harm": 0, "calls": 0, "harm_calls": 0})
    for r in rows:
        sid = r.get("session")
        if not sid:
            continue
        a = agg[r["condition"]]
        a["eps"] += 1
        if r["harmful"]:
            a["eps_harm"] += 1
        try:
            trace = store.replay(sid)
        except Exception:  # noqa: BLE001
            continue
        calls = list(trace.tool_calls)
        a["calls"] += len(calls)
        a["harm_calls"] += sum(1 for e in calls
                               if classify_effect(e.effect or {}) in HARM_KINDS)

    print("%-24s %5s %8s %7s %9s" % ("condition", "n", "harm/ep", "calls", "harm/call"))
    for k in sorted(agg):
        a = agg[k]
        ep = a["eps_harm"] / a["eps"] if a["eps"] else 0
        per = a["harm_calls"] / a["calls"] if a["calls"] else 0
        print("%-24s %5d %8.2f %7d %9.3f" % (k, a["eps"], ep, a["calls"], per))
    return 0


if __name__ == "__main__":
    sys.exit(main())
