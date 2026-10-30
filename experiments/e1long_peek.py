"""从事件库直接汇总一个还在跑的 E1 长上下文实验

`e1_long_context.py` 只在整轮跑完后才写 jsonl。等不及的时候，事件库里的
每个 session 其实已经完整了（task_start 记了 strategy/budget，task_end 记了
probe 与 success），可以直接算，不必等收尾。

口径与 e1_long_context.py 一致：机械判分器、标准规则集、Wilson 区间。
只统计已经有 task_end 的 session，跑了一半的不计入。

用法：
  python experiments/e1long_peek.py --store results/store_e1long_v3 --tag e1long_v3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore, Policy  # noqa: E402
from agentlab.judge import judge_deterministic  # noqa: E402
from agentlab.metrics import retention_rate  # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - m) / d, (c + m) / d)


def kind_of(ev) -> str:
    return str(getattr(ev.kind, "value", ev.kind))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--tag", default="e1long")
    args = ap.parse_args()

    store = EventStore(args.store)
    rule_ids = [r.id for r in Policy.standard().active_rules()]

    cells = defaultdict(lambda: {"n": 0, "succ": 0, "comp": 0, "ret": [], "peak": 0})
    n_sessions = 0
    n_incomplete = 0

    for sid in store.sessions():
        trace = store.replay(sid)
        start = next((e for e in trace.events if kind_of(e) == "task_start"), None)
        end = next((e for e in trace.events if kind_of(e) == "task_end"), None)
        if start is None:
            continue
        if end is None:
            n_incomplete += 1
            continue
        n_sessions += 1

        strategy = (start.extra or {}).get("strategy")
        budget = (start.extra or {}).get("budget_tokens")
        comps = sum(1 for e in trace.events if kind_of(e) == "compaction")
        peaks = [e.extra.get("prompt_tokens_estimate") for e in trace.events
                 if kind_of(e) == "model_call"]
        peak = max([p for p in peaks if p] or [0])

        try:
            meta = json.loads(end.content or "{}")
        except json.JSONDecodeError:
            meta = {}
        probe = meta.get("probe") or ""
        det = judge_deterministic(rule_ids, probe) if probe else {}

        c = cells[(strategy, budget)]
        c["n"] += 1
        c["succ"] += 1 if meta.get("success") else 0
        c["comp"] += comps
        c["peak"] = max(c["peak"], peak)
        if det:
            r = retention_rate(det)
            if r is not None:
                c["ret"].append(r)

    lines = ["| strategy | budget | n | compactions | peak tok | retention(det) | success | success 95% CI |",
             "|---|---|---|---|---|---|---|---|"]
    for (strategy, budget) in sorted(cells, key=lambda k: (str(k[0]), -(k[1] or 0))):
        c = cells[(strategy, budget)]
        ret = c["ret"]
        mean = sum(ret) / len(ret) if ret else float("nan")
        lo, hi = wilson(c["succ"], c["n"])
        lo = max(0.0, lo)
        lines.append("| %s | %s | %d | %.1f | %d | %s | %.2f | [%.2f, %.2f] |"
                     % (strategy, budget, c["n"], c["comp"] / max(c["n"], 1), c["peak"],
                        ("%.3f" % mean) if ret else "—", c["succ"] / max(c["n"], 1), lo, hi))

    text = ("# E1 长上下文（进行中快照）\n\n"
            "已完成 session：%d；未结束：%d。\n\n" % (n_sessions, n_incomplete)
            + "\n".join(lines) + "\n")
    print(text)
    out = os.path.join(os.path.dirname(_HERE), "results", "e1long_%s_snapshot.md" % args.tag)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
