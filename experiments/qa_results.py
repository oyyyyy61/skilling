"""结果质检：在写报告之前先确认数据没坏

之前踩过的坑都是"数据看起来正常但其实是坏的"：
  - tag 复用导致同一个 session id 里堆了多个 episode，重放时事件混在一起
  - 端口占用导致整批 episode 秒退，得到的"全部失败"是假数据
  - 早期版本的脚本产出的文件混进了结论

这个脚本对每个结果文件做四项检查，任何一项不过就明确标出来，
免得又靠肉眼发现。

用法：
  python experiments/qa_results.py --dir results
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402

# 已知作废/被取代的文件，不应进入任何结论
EXCLUDED = {
    "e1_e1_full.jsonl", "e2_e2_v1.jsonl", "e4_e4_full.jsonl",
    "e3_e3_pilot.jsonl", "e6_e6_v1.jsonl", "e7_pilot", "e1b_e1b_pilot.jsonl",
}


def check_file(path: str, store_cache: dict) -> dict:
    rows = []
    bad_lines = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines += 1

    sids = [r.get("session") for r in rows if r.get("session")]
    dup_in_file = [s for s, c in Counter(sids).items() if c > 1]

    issues = []
    notes = []
    if bad_lines:
        issues.append("坏行 %d" % bad_lines)
    if dup_in_file:
        # The reproducibility check repeats the same seed on purpose, so a
        # repeated session id there is the design, not corruption.
        if "repro" in os.path.basename(path):
            notes.append("重复 session %d（复现实验按设计重跑同种子）" % len(dup_in_file))
        else:
            issues.append("文件内重复 session %d" % len(dup_in_file))

    # 0 成功的整批结果通常是环境故障（端口占用、服务未起），不是模型行为。
    # 只在文件确实记录了 success 字段时才判，否则会误伤复现实验这类不含该字段的数据。
    if rows:
        has_succ_key = sum(1 for r in rows if "success" in r)
        succ = [r for r in rows if r.get("success") is True]
        if has_succ_key >= 0.8 * len(rows) and not succ and len(rows) >= 10:
            issues.append("全部失败(%d) 疑似环境故障" % len(rows))

    # 同一 session 出现多个 task_start 可能是 tag 复用导致的污染，也可能
    # 只是"跑了两遍、事件库被追加"。单看 task_start 个数无法区分，
    # 真正的判据见 diag_dup.py（比较行内计数与 replay 是否一致）。
    multi_start = []
    for sid in set(sids):
        if sid not in store_cache:
            continue
        trace = store_cache[sid]
        n = sum(1 for e in trace.events
                if str(getattr(e.kind, "value", e.kind)) == "task_start")
        if n > 1:
            multi_start.append((sid, n))
    if multi_start:
        if "repro" in os.path.basename(path):
            notes.append("多 task_start %d（复现实验按设计复用 session id）" % len(multi_start))
        else:
            issues.append("session 含多个 task_start: %s（用 diag_dup.py 核实行是否被混算）"
                          % multi_start[:3])

    return {
        "file": os.path.basename(path),
        "episodes": len(rows),
        "excluded": os.path.basename(path) in EXCLUDED,
        "issues": issues,
        "notes": notes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results")
    ap.add_argument("--store-root", default=None,
                    help="若给出，则用事件库检查 session 是否被 tag 复用污染")
    args = ap.parse_args()

    cache = {}
    if args.store_root:
        for d in glob.glob(os.path.join(args.store_root, "*")):
            if not os.path.isdir(d):
                continue
            try:
                st = EventStore(d)
            except Exception:  # noqa: BLE001
                continue
            for sid in st.sessions():
                try:
                    cache[sid] = st.replay(sid)
                except Exception:  # noqa: BLE001
                    pass

    results = [check_file(p, cache) for p in sorted(glob.glob(os.path.join(args.dir, "*.jsonl")))]
    if not results:
        print("no jsonl found in %s" % args.dir)
        return 1

    print("%-38s %8s %8s  %s" % ("file", "episodes", "excluded", "issues / notes"))
    print("-" * 100)
    bad = 0
    for r in results:
        flag = "EXCLUDED" if r["excluded"] else ""
        detail = "; ".join(r["issues"])
        if r["notes"]:
            detail = (detail + " | " if detail else "") + "; ".join(r["notes"])
        print("%-38s %8d %8s  %s" % (r["file"], r["episodes"], flag, detail or "ok"))
        if r["issues"]:
            bad += 1
    print("\n%d files, %d with issues" % (len(results), bad))
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
