"""通过性检查：固定 seed 后，同一条件是否可复现？

这是阶段 1 的分叉点。如果同一 seed 两次运行的规则保持率仍然不同，
说明"压缩导致规则丢失"是随机事件而非稳定机制，所有结论都要改成分布描述。

检查三层：
  1. 逐轮模型输出是否逐字节相同（最严格）
  2. 压缩摘要内容是否相同
  3. 规则保持率是否相同（结论层）

用法：
  python experiments/check_reproducibility.py --tasks A1,A4,B5 --budget 550
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import (  # noqa: E402
    Episode, EventStore, LLMClient, Policy, TASK_BY_ID, TokenizerCounter,
    judge_rule_recall, retention_rate,
)

DEFAULT_TOKENIZER = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"


def h(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def one_run(task_id, strategy, budget, seed, llm, judge, store, root, tag, tk):
    task = TASK_BY_ID[task_id]
    policy = Policy.standard()
    ep = Episode(
        task=task,
        policy=policy,
        llm=llm,
        store=store,
        root=os.path.join(root, "%s_%s_s%d" % (task_id, strategy, seed)),
        strategy=strategy,
        budget_tokens=budget,
        mode="enforced",
        probe_at_end=True,
        tag="%s_s%d" % (tag, seed),
        seed=seed,
        tokenizer=tk,
    )
    res = ep.run()
    trace = store.replay(res.session_id)
    model_calls = [h(e.content) for e in trace.events if e.kind == "model_call"]
    compactions = [h((e.extra or {}).get("rendered", "")) for e in trace.events if e.kind == "compaction"]
    scores = judge_rule_recall(judge, policy.active_rules(), res.rule_recall or "") if res.rule_recall else {}
    return {
        "task_id": task_id,
        "strategy": strategy,
        "seed": seed,
        "model_calls": model_calls,
        "compactions": compactions,
        "retention": retention_rate(scores),
        "retention_detail": scores,
        "turns": res.turns,
        "compaction_count": res.compactions,
        "completed": res.completed,
        "terminated_by": res.terminated_by,
        "session": res.session_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="A1,A4,B5")
    ap.add_argument("--strategy", default="uniform_summary")
    ap.add_argument("--budget", type=int, default=550)
    ap.add_argument("--seeds", default="1,1,2,3",
                    help="重复同一 seed 即测可复现性；不同 seed 测采样分布")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default="repro")
    args = ap.parse_args()

    tk = TokenizerCounter(path=args.tokenizer)
    print("tokenizer: %s" % tk.source, flush=True)
    if tk.tok is None:
        print("  WARNING: tokenizer not loaded, falling back to heuristic: %s" % getattr(tk, "error", ""), flush=True)

    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    store = EventStore(os.path.join(outdir, "store_" + args.tag))
    root = os.path.join(outdir, "runs_" + args.tag)
    llm = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=512)
    judge = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=256)

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    rows = []
    for task_id in tasks:
        for seed in seeds:
            print("[%s seed=%d]" % (task_id, seed), flush=True)
            row = one_run(task_id, args.strategy, args.budget, seed, llm, judge, store, root, args.tag, tk)
            rows.append(row)
            print("   retention=%s compactions=%d turns=%d completed=%s"
                  % (row["retention"], row["compaction_count"], row["turns"], row["completed"]), flush=True)

    print("\n=== 可复现性判定 ===")
    verdict = {}
    for task_id in tasks:
        same_seed = [r for r in rows if r["task_id"] == task_id and r["seed"] == seeds[0]]
        if len(same_seed) < 2:
            continue
        a, b = same_seed[0], same_seed[1]
        same_calls = a["model_calls"] == b["model_calls"]
        same_comp = a["compactions"] == b["compactions"]
        same_ret = a["retention"] == b["retention"]
        verdict[task_id] = {"identical_outputs": same_calls, "identical_compaction": same_comp,
                            "identical_retention": same_ret}
        print("%-4s 逐轮输出一致=%-5s 压缩内容一致=%-5s 保持率一致=%-5s (%s vs %s)"
              % (task_id, same_calls, same_comp, same_ret, a["retention"], b["retention"]))

    by_task = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r["retention"])
    print("\n不同 seed 的保持率分布：")
    for task_id, vals in by_task.items():
        print("  %-4s %s" % (task_id, " ".join("%.2f" % v for v in vals)))

    with open(os.path.join(outdir, "repro_%s.jsonl" % args.tag), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.write(json.dumps({"verdict": verdict}, ensure_ascii=False) + "\n")
    print("\nwrote %s/repro_%s.jsonl" % (outdir, args.tag))

    all_identical = all(v["identical_outputs"] for v in verdict.values()) and len(verdict) > 0
    print("\n结论：%s" % ("固定 seed 可复现 —— 走稳定机制路线" if all_identical
                         else "固定 seed 仍不可复现 —— 必须走重复采样 + 区间路线"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
