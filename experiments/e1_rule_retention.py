"""E1: does rule retention survive context compaction?

Design (section 6.1 of the research plan)
-----------------------------------------
Holds fixed: task, model, decoding temperature, tool set, rule set.
Varies: the compaction strategy, which is the only thing that decides what
happens to the rule block when the context is rewritten.

Measures per run:
  success           -- did the legitimate task actually get done
  retention         -- semantic rule recall, scored by a judge
  harness_retention -- was the rule wording still in the prompt at all
  violations        -- forbidden tool calls the model attempted
  compactions       -- how many rewrites happened

Usage:
  python experiments/e1_rule_retention.py --tasks A1,A3,B1 --budget 1200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import (  # noqa: E402
    Episode, EventStore, LLMClient, Policy, TASK_BY_ID, aggregate,
    format_table, harness_retention, judge_rule_recall, retention_rate,
)
from agentlab.context import STRATEGIES  # noqa: E402


def run_one(task_id, strategy, llm, judge_llm, store, root, budget, mode, tag) -> dict:
    task = TASK_BY_ID[task_id]
    policy = Policy.standard()
    ep = Episode(
        task=task,
        policy=policy,
        llm=llm,
        store=store,
        root=os.path.join(root, tag, "%s_%s" % (task_id, strategy)),
        strategy=strategy,
        budget_tokens=budget,
        mode=mode,
        probe_at_end=True,
        tag="%s_b%d" % (tag, budget),  # budget must be part of the session id
    )
    t0 = time.time()
    result = ep.run()
    elapsed = time.time() - t0

    trace = store.replay(result.session_id)
    rules = policy.active_rules()
    scores = judge_rule_recall(judge_llm, rules, result.rule_recall or "") if result.rule_recall else {}
    hr = harness_retention(trace)

    row = {
        "task_id": task_id,
        "strategy": strategy,
        "budget": budget,
        "mode": mode,
        "success": result.success,
        "turns": result.turns,
        "violations": result.violations,
        "blocked": result.blocked,
        "compactions": result.compactions,
        "over_refused": result.over_refused,
        "retention": retention_rate(scores),
        "retention_detail": scores,
        "harness_retention": hr,
        "elapsed_s": round(elapsed, 1),
        "session": result.session_id,
        "probe": (result.rule_recall or "")[:1200],
        "llm": result.llm_stats,
    }
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="A1,A4,B1,B5")
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--budgets", default="1200,800,550",
                    help="comma list; 1200 -> no compaction, 800 -> ~1, 550 -> several")
    ap.add_argument("--mode", default="enforced", choices=["enforced", "open"])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or time.strftime("e1_%Y%m%d_%H%M%S")
    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    store = EventStore(os.path.join(outdir, "store_" + tag))
    root = os.path.join(outdir, "runs_" + tag)

    llm = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=512)
    judge = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=256)

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    rows = []
    total = len(tasks) * len(strategies) * len(budgets)
    i = 0
    for task_id in tasks:
        for strategy in strategies:
            for budget in budgets:
                i += 1
                print("[%d/%d] %s / %s / b=%d" % (i, total, task_id, strategy, budget), flush=True)
                try:
                    row = run_one(task_id, strategy, llm, judge, store, root, budget, args.mode, tag)
                except Exception as e:  # noqa: BLE001
                    print("   FAILED: %s" % e, flush=True)
                    row = {"task_id": task_id, "strategy": strategy, "budget": budget, "mode": args.mode,
                           "success": False, "turns": 0, "violations": 0, "blocked": 0,
                           "compactions": 0, "over_refused": False, "retention": None,
                           "retention_detail": {}, "harness_retention": {}, "error": str(e)}
                rows.append(row)
                print(
                    "   success=%s retention=%s violations=%d compactions=%d %.1fs"
                    % (
                        row.get("success"),
                        ("%.2f" % row["retention"]) if row.get("retention") is not None else "-",
                        row.get("violations", 0),
                        row.get("compactions", 0),
                        row.get("elapsed_s", 0),
                    ),
                    flush=True,
                )

    table = aggregate(rows)
    print("\n" + format_table(table))

    with open(os.path.join(outdir, "e1_%s.jsonl" % tag), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(outdir, "e1_%s.md" % tag), "w", encoding="utf-8") as f:
        f.write("# E1 rule retention\n\n")
        f.write("budgets=%s, mode=%s, tasks=%s\n\n" % (args.budgets, args.mode, ",".join(tasks)))
        f.write("```\n" + format_table(table) + "\n```\n\n## per run\n\n")
        f.write("| task | strategy | budget | success | retention | violations | compactions |\n|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(
                "| %s | %s | %s | %s | %s | %d | %d |\n"
                % (
                    r.get("task_id"),
                    r.get("strategy"),
                    r.get("budget"),
                    r.get("success"),
                    ("%.2f" % r["retention"]) if r.get("retention") is not None else "-",
                    r.get("violations", 0),
                    r.get("compactions", 0),
                )
            )
    print("\nwrote %s/e1_%s.{jsonl,md}" % (outdir, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
