"""E1 长上下文版：在 ~10K token 的真实上下文里测压缩悬崖

阶段 0 与 E1b 的上下文只有 1–3K token，规则块离上下文头部很近，
压缩能造成的损失被这个尺度限制住了。本实验用任务 B8（读 8 个 ~2.1K 字符的
文档）把单个 episode 顶到约 9.6K token，再用 token 预算直接控制压缩次数。

预算校准（calibrate_budget.py B8）：
  12000 -> 0 次压缩（峰值 prompt 9582）
   9000 -> 1 次
   6000 -> 5 次
   4000 -> 9 次

每格 3 次重复，同时报自评判分与机械判分（--det-judge）两种保持率。

用法：
  python experiments/e1_long_context.py --budgets 12000,9000,6000,4000 --repeats 3
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
    cohen_kappa, judge_deterministic, judge_rule_recall, retention_rate,
)

DEFAULT_TOKENIZER = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"


def run_one(task_id, strategy, budget, rep, llm, judge, store, root, tag, tk):
    task = TASK_BY_ID[task_id]
    policy = Policy.standard()
    rule_ids = [r.id for r in policy.active_rules()]
    ep = Episode(
        task=task,
        policy=policy,
        llm=llm,
        store=store,
        root=os.path.join(root, "%s_%s_b%d_r%d" % (task_id, strategy, budget, rep)),
        strategy=strategy,
        budget_tokens=budget,
        mode="enforced",
        probe_at_end=True,
        tag="%s_b%d_r%d" % (tag, budget, rep),
        seed=None,
        tokenizer=tk,
    )
    t0 = time.time()
    res = ep.run()
    trace = store.replay(res.session_id)

    probe = res.rule_recall or ""
    llm_scores = judge_rule_recall(judge, policy.active_rules(), probe) if probe else {}
    det_scores = judge_deterministic(rule_ids, probe) if probe else {}
    prompt_sizes = [
        e.extra.get("prompt_tokens_estimate")
        for e in trace.events
        if str(getattr(e.kind, "value", e.kind)) == "model_call"
    ]
    prompt_sizes = [p for p in prompt_sizes if p]

    return {
        "task_id": task_id,
        "strategy": strategy,
        "budget": budget,
        "rep": rep,
        "success": res.success,
        "completed": res.completed,
        "terminated_by": res.terminated_by,
        "violations": res.violations,
        "blocked": res.blocked,
        "compactions": res.compactions,
        "retention_llm": retention_rate(llm_scores) if llm_scores else None,
        "retention_det": retention_rate(det_scores) if det_scores else None,
        "llm_detail": llm_scores,
        "det_detail": det_scores,
        "peak_prompt_tokens": max(prompt_sizes) if prompt_sizes else None,
        "turns": res.turns,
        "elapsed_s": round(time.time() - t0, 1),
        "session": res.session_id,
    }


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - m) / d, (c + m) / d)


def aggregate(rows, budgets, strategies):
    out = []
    for strategy in strategies:
        for budget in budgets:
            items = [r for r in rows if r["strategy"] == strategy and r["budget"] == budget]
            if not items:
                continue
            n = len(items)
            comp = [r["compactions"] for r in items]
            llm_r = [r["retention_llm"] for r in items if r["retention_llm"] is not None]
            det_r = [r["retention_det"] for r in items if r["retention_det"] is not None]
            peaks = [r["peak_prompt_tokens"] for r in items if r["peak_prompt_tokens"]]
            k_succ = sum(1 for r in items if r["success"])
            lo, hi = wilson(k_succ, n)
            out.append({
                "strategy": strategy,
                "budget": budget,
                "n": n,
                "compactions_mean": round(st.mean(comp), 1) if comp else 0,
                "peak_tokens": round(st.mean(peaks)) if peaks else "-",
                "retention_llm": round(st.mean(llm_r), 3) if llm_r else None,
                "retention_det": round(st.mean(det_r), 3) if det_r else None,
                "ret_min": round(min(det_r), 2) if det_r else None,
                "ret_max": round(max(det_r), 2) if det_r else None,
                "success_rate": round(k_succ / n, 2),
                "succ_ci_low": round(lo, 2),
                "succ_ci_high": round(hi, 2),
                "completed_rate": round(sum(1 for r in items if r["completed"]) / n, 2),
                "violation_rate": round(sum(1 for r in items if r["violations"]) / n, 2),
            })
    return out


def table(rows):
    cols = ["strategy", "budget", "n", "compactions_mean", "peak_tokens", "retention_llm",
            "retention_det", "ret_min", "ret_max", "success_rate", "succ_ci_low", "succ_ci_high",
            "completed_rate", "violation_rate"]
    widths = {c: max(len(c), *(len(str(r.get(c))) for r in rows)) for c in cols}
    lines = ["  ".join(c.ljust(widths[c]) for c in cols), "-" * (sum(widths.values()) + 2 * len(cols))]
    for r in rows:
        lines.append("  ".join(str(r.get(c)).ljust(widths[c]) for c in cols))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="B8")
    ap.add_argument("--strategies", default="uniform_summary,typed_summary,typed_summary_protected")
    ap.add_argument("--budgets", default="12000,9000,6000,4000")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or time.strftime("e1long_%H%M%S")
    tk = TokenizerCounter(path=args.tokenizer)
    print("tokenizer: %s" % tk.source, flush=True)

    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    store = EventStore(os.path.join(outdir, "store_" + tag))
    root = os.path.join(outdir, "runs_" + tag)
    llm = LLMClient(base_url=args.base_url, model=args.model, temperature=args.temperature, max_tokens=512)
    judge = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=256)

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    rows = []
    total = len(tasks) * len(strategies) * len(budgets) * args.repeats
    i = 0
    for task_id in tasks:
        for strategy in strategies:
            for budget in budgets:
                for rep in range(args.repeats):
                    i += 1
                    print("[%d/%d] %s %s b=%d rep=%d" % (i, total, task_id, strategy, budget, rep), flush=True)
                    try:
                        row = run_one(task_id, strategy, budget, rep, llm, judge, store, root, tag, tk)
                    except Exception as e:  # noqa: BLE001
                        print("   FAILED %s" % e, flush=True)
                        row = {"task_id": task_id, "strategy": strategy, "budget": budget, "rep": rep,
                               "success": False, "completed": False, "terminated_by": "error",
                               "violations": 0, "blocked": 0, "compactions": 0,
                               "retention_llm": None, "retention_det": None, "llm_detail": {},
                               "det_detail": {}, "peak_prompt_tokens": None, "turns": 0,
                               "elapsed_s": 0, "error": str(e)}
                    rows.append(row)
                    print("   compact=%d peak=%s ret_llm=%s ret_det=%s succ=%s %.0fs"
                          % (row["compactions"], row["peak_prompt_tokens"],
                             row["retention_llm"], row["retention_det"], row["success"],
                             row["elapsed_s"]), flush=True)

    agg = aggregate(rows, budgets, strategies)
    print("\n" + table(agg))

    with open(os.path.join(outdir, "e1long_%s.jsonl" % tag), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(outdir, "e1long_%s.md" % tag), "w", encoding="utf-8") as f:
        f.write("# E1 long-context compaction\n\n")
        f.write("task=%s budgets=%s repeats=%d\n\n```\n%s\n```\n"
                % (args.tasks, args.budgets, args.repeats, table(agg)))
    print("\nwrote %s/e1long_%s.{jsonl,md}" % (outdir, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
