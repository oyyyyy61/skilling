"""E1b: 用"每 K 轮强制压缩"作为干净的自变量。

阶段 0 用 token 预算间接控制压缩次数，实测发现同一预算在不同任务上
压缩 1 次到 8 次不等（任务轨迹长度不同），把任务难度混进了自变量。
这里改成直接指定压缩频率：K = 0（不压缩）/ 10（约 1 次）/ 4（约 3 次）/ 2（约 6 次）。

用法：
  python experiments/e1b_forced_compaction.py --tasks A1,A4,B1,B5 --every 0,10,4,2 --repeats 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import (  # noqa: E402
    Episode, EventStore, LLMClient, Policy, TASK_BY_ID, TokenizerCounter,
    judge_rule_recall, retention_rate,
)

DEFAULT_TOKENIZER = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"


def run_one(task_id, strategy, every, rep, llm, judge, store, root, tag, tk, budget):
    task = TASK_BY_ID[task_id]
    policy = Policy.standard()
    ep = Episode(
        task=task,
        policy=policy,
        llm=llm,
        store=store,
        root=os.path.join(root, "%s_%s_k%d_r%d" % (task_id, strategy, every, rep)),
        strategy=strategy,
        budget_tokens=budget,
        mode="enforced",
        probe_at_end=True,
        tag="%s_k%d_r%d" % (tag, every, rep),
        seed=None,  # sampling variation is part of the design here
        tokenizer=tk,
        compact_every=every,
    )
    t0 = time.time()
    res = ep.run()
    trace = store.replay(res.session_id)
    scores = judge_rule_recall(judge, policy.active_rules(), res.rule_recall or "") if res.rule_recall else {}
    return {
        "task_id": task_id,
        "strategy": strategy,
        "compact_every": every,
        "rep": rep,
        "success": res.success,
        "completed": res.completed,
        "terminated_by": res.terminated_by,
        "retention": retention_rate(scores),
        "retention_detail": scores,
        "turns": res.turns,
        "compactions": res.compactions,
        "violations": res.violations,
        "blocked": res.blocked,
        "elapsed_s": round(time.time() - t0, 1),
        "session": res.session_id,
    }


def aggregate(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["strategy"], r["compact_every"]), []).append(r)
    out = []
    for (strategy, every), items in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        rets = [r["retention"] for r in items if r.get("retention") is not None]
        out.append({
            "strategy": strategy,
            "every": every,
            "n": len(items),
            "compactions_mean": round(st.mean(r["compactions"] for r in items), 1),
            "retention_mean": round(st.mean(rets), 3) if rets else None,
            "retention_min": round(min(rets), 2) if rets else None,
            "retention_max": round(max(rets), 2) if rets else None,
            "success_rate": round(sum(1 for r in items if r["success"]) / len(items), 2),
            "completed_rate": round(sum(1 for r in items if r["completed"]) / len(items), 2),
            "violation_rate": round(sum(1 for r in items if r["violations"] > 0) / len(items), 2),
        })
    return out


def table(rows):
    cols = ["strategy", "every", "n", "compactions_mean", "retention_mean", "retention_min",
            "retention_max", "success_rate", "completed_rate", "violation_rate"]
    widths = {c: max(len(c), *(len(str(r.get(c))) for r in rows)) for c in cols}
    lines = ["  ".join(c.ljust(widths[c]) for c in cols), "-" * (sum(widths.values()) + 2 * len(cols))]
    for r in rows:
        lines.append("  ".join(str(r.get(c)).ljust(widths[c]) for c in cols))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="A1,A4,B1,B5")
    ap.add_argument("--strategies", default="uniform_summary,typed_summary,typed_summary_protected")
    ap.add_argument("--every", default="0,10,4,2", help="0 = 不压缩")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--budget", type=int, default=32768, help="足够大，避免预算触发额外压缩")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or time.strftime("e1b_%H%M%S")
    tk = TokenizerCounter(path=args.tokenizer)
    print("tokenizer: %s" % tk.source, flush=True)
    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    store = EventStore(os.path.join(outdir, "store_" + tag))
    root = os.path.join(outdir, "runs_" + tag)
    llm = LLMClient(base_url=args.base_url, model=args.model, temperature=0.7, max_tokens=512)
    judge = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=256)

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    everys = [int(x) for x in args.every.split(",") if x.strip()]

    rows = []
    total = len(tasks) * len(strategies) * len(everys) * args.repeats
    i = 0
    for task_id in tasks:
        for strategy in strategies:
            for every in everys:
                for rep in range(args.repeats):
                    i += 1
                    print("[%d/%d] %s %s k=%d rep=%d" % (i, total, task_id, strategy, every, rep), flush=True)
                    try:
                        row = run_one(task_id, strategy, every, rep, llm, judge, store, root, tag, tk, args.budget)
                    except Exception as e:  # noqa: BLE001
                        print("   FAILED %s" % e, flush=True)
                        row = {"task_id": task_id, "strategy": strategy, "compact_every": every, "rep": rep,
                               "success": False, "completed": False, "terminated_by": "error",
                               "retention": None, "retention_detail": {}, "turns": 0, "compactions": 0,
                               "violations": 0, "blocked": 0, "elapsed_s": 0, "error": str(e)}
                    rows.append(row)
                    print("   ret=%s comp=%d turns=%d completed=%s viol=%d %.1fs"
                          % (row.get("retention"), row.get("compactions", 0), row.get("turns", 0),
                             row.get("completed"), row.get("violations", 0), row.get("elapsed_s", 0)), flush=True)

    agg = aggregate(rows)
    print("\n" + table(agg))
    with open(os.path.join(outdir, "e1b_%s.jsonl" % tag), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(outdir, "e1b_%s.md" % tag), "w", encoding="utf-8") as f:
        f.write("# E1b forced-compaction experiment\n\n```\n%s\n```\n" % table(agg))
    print("\nwrote %s/e1b_%s.{jsonl,md}" % (outdir, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
