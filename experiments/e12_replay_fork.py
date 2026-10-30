"""E12: 在第 k 轮分叉（近似重放）

E11 在第 0 轮分叉，冒烟结果显示两个条件都是 0/2、首动作一律是读取——
分叉点太早，模型还没进入"决定往哪写"的位置，所以什么也测不到。

这里换成在**第 k 轮**分叉：从事件库取出真实轨迹里的前 k 步（模型的原始输出 +
工具返回），重建那一刻的上下文，然后在系统提示里放/不放规则，各采样 N 次，
看接下来的动作会不会跨边界。

**这是近似重放，不是精确重放。** 事件库只存了工具输出的前 400 字符
（`evidence.output_preview`），而真实上下文里放的是前 2500 字符。
所以模型看到的返回比当时短。这一点对"绝对越界率"有影响，
但两个条件用的是**完全相同**的上下文，只有规则不同，所以条件间的差异仍然可比。

用法：
  python experiments/e12_replay_fork.py --store results/store_e7_v2 \
      --jsonl results/e7_e7_v2.jsonl --turn 3 --samples 10 --tasks T2,T4 --tag e12_v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore, LLMClient, Policy  # noqa: E402
from agentlab.agent import SYSTEM_TEMPLATE, parse_tool_call  # noqa: E402
from agentlab.tools import tools_prompt  # noqa: E402

sys.path.insert(0, _HERE)
from e11_rule_fork import crosses, wilson  # noqa: E402


def kind_of(ev) -> str:
    return str(getattr(ev.kind, "value", ev.kind))


MUTATING = ("fs_write", "fs_append", "db_exec", "net_get")


def replay_prefix(store: EventStore, sid: str, k: int):
    """取该 session 前 k 步：(task_id, instruction, [(assistant_raw, tool, preview), ...])

    k 为 None 时自适应：取"第一次出现写类动作"之前的位置。这样分叉点落在
    "已经读完、正要动手"的那一刻，而不是盲选的第 k 轮（那往往还在纯读取阶段，
    两个条件都只会继续读，测不出差别）。
    """
    trace = store.replay(sid)
    instruction = None
    task_id = None
    steps = []
    for ev in trace.events:
        kk = kind_of(ev)
        if kk == "task_start":
            instruction = (ev.extra or {}).get("instruction")
            task_id = ev.task_id
        elif kk == "model_call":
            steps.append([ev.content or "", None, None])
        elif kk == "tool_call":
            call = ev.tool_call or {}
            if not steps:
                continue
            steps[-1][1] = str(call.get("name"))
            steps[-1][2] = (ev.evidence or {}).get("output_preview") or ""
    # 只保留已经拿到工具返回的完整步
    steps = [s for s in steps if s[1]]
    if k is None:
        first_mut = next((i for i, s in enumerate(steps) if s[1] in MUTATING), None)
        if first_mut is None:
            k = min(3, len(steps))
        else:
            k = max(1, first_mut)  # 分叉在动手之前；至少要保留第一步
    return task_id, instruction, steps[:k]


def build_messages(instruction: str, steps: list, with_rules: bool) -> list[dict]:
    policy = Policy.standard() if with_rules else Policy(rules=[], version="policy.empty")
    msgs = [
        {"role": "system", "content": SYSTEM_TEMPLATE.format(
            rules=policy.system_text(), tools=tools_prompt())},
        {"role": "user", "content": instruction or ""},
    ]
    for raw, tool, preview in steps:
        msgs.append({"role": "assistant", "content": raw[:1500]})
        msgs.append({"role": "user",
                     "content": "[工具 %s 输出]\n%s" % (tool, preview)})
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--tasks", default="T2,T4")
    ap.add_argument("--turn", default="auto",
                    help="分叉在第几步；'auto' 表示取第一次写类动作之前")
    ap.add_argument("--sessions", type=int, default=3, help="每个任务取几条轨迹")
    ap.add_argument("--samples", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default="e12_v1")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    store = EventStore(args.store)
    llm = LLMClient(base_url=args.base_url, model=args.model,
                    temperature=args.temperature, max_tokens=200)

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    turn = None if str(args.turn) == "auto" else int(args.turn)
    agg = defaultdict(lambda: {"n": 0, "cross": 0})
    out_rows = []
    fork_points = []

    for task_id in tasks:
        picked = [r for r in rows if r["task_id"] == task_id and r.get("session")]
        picked = picked[:args.sessions]
        for r in picked:
            tid, instr, steps = replay_prefix(store, r["session"], turn)
            if not steps:
                print("skip %s (no steps)" % r["session"], flush=True)
                continue
            fork_points.append((task_id, len(steps)))
            for cond, with_rules in (("rules", True), ("no_rules", False)):
                msgs = build_messages(instr, steps, with_rules)
                for _ in range(args.samples):
                    try:
                        raw = llm.chat(msgs, max_tokens=200)
                    except Exception as e:  # noqa: BLE001
                        print("FAILED %s" % e, flush=True)
                        continue
                    call = parse_tool_call(raw) or {}
                    hit = crosses(task_id, call)
                    a = agg[(task_id, cond)]
                    a["n"] += 1
                    a["cross"] += int(hit)
                    out_rows.append({"task": task_id, "cond": cond, "session": r["session"],
                                     "tool": str(call.get("tool")), "crosses": hit})

    lines = ["| 任务 | 条件 | n | 越界 | 比例 | 95% CI |", "|---|---|---|---|---|---|"]
    for task_id in tasks:
        for cond in ("rules", "no_rules"):
            a = agg.get((task_id, cond))
            if not a or not a["n"]:
                continue
            lo, hi = wilson(a["cross"], a["n"])
            lines.append("| %s | %s | %d | %d | %.2f | [%.2f, %.2f] |"
                         % (task_id, cond, a["n"], a["cross"],
                            a["cross"] / a["n"], max(0.0, lo), hi))
    text = ("# E12 第 k 轮分叉（近似重放）\n\n"
            "工具输出截断到 400 字符（事件库只存了这么多）。两条件上下文完全相同，"
            "只有系统提示里的规则不同。\n\n"
            "分叉点：%s。实际分叉位置：%s\n\n"
            % (args.turn, ", ".join("%s@%d" % (t, n) for t, n in fork_points))) \
        + "\n".join(lines) + "\n"
    print(text)

    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "e12_%s.md" % args.tag), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(outdir, "e12_%s.jsonl" % args.tag), "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote %s/e12_%s.{md,jsonl}" % (outdir, args.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
