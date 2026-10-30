"""诊断：session 里出现多个 task_start 时，jsonl 里的行还可不可信

qa_results 发现 e3b_full / e4_v2 的每个 session 有 2 个 task_start。
这可能是"整批跑了两遍、事件库被追加"，那样 episode 内部用 replay 算出来的
violations / blocked / compactions 就会把两遍的事件混在一起。

判定方法：对同一个 session，比较
  (a) 事件库里 task_start 的个数
  (b) jsonl 里该 session 的行数
  (c) 行里记录的 violations/blocked  与  当前 replay 出来的值
如果 (c) 相等而 (a)=2，说明重复发生在该行写完之后，行本身没被污染。
如果 (c) 不等，说明该行是混算的，结论不能用。

用法：
  python experiments/diag_dup.py --jsonl results/e3b_e3b_full.jsonl --store results/store_e3b_full
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    rows = []
    with open(args.jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    by_sid = Counter(r.get("session") for r in rows if r.get("session"))
    store = EventStore(args.store)

    n_multi = 0
    n_row_mismatch = 0
    shown = 0
    print("%-46s %6s %5s %5s %6s %6s" % ("session", "starts", "rows", "turns", "row_vio", "rep_vio"))
    for sid, n_rows in sorted(by_sid.items()):
        if sid not in store.sessions():
            print("%-46s MISSING FROM STORE" % sid[:46])
            continue
        trace = store.replay(sid)
        n_start = sum(1 for e in trace.events
                      if str(getattr(e.kind, "value", e.kind)) == "task_start")
        if n_start <= 1:
            continue
        n_multi += 1
        rep_vio = len(trace.violations)
        row = next(r for r in rows if r.get("session") == sid)
        row_vio = row.get("violations")
        same = (row_vio == rep_vio)
        if not same:
            n_row_mismatch += 1
        if shown < args.limit:
            print("%-46s %6d %5d %5s %6s %6s  %s"
                  % (sid[:46], n_start, n_rows, row.get("turns"),
                     row_vio, rep_vio, "same" if same else "MISMATCH"))
            shown += 1

    print("\nsessions with >1 task_start: %d" % n_multi)
    print("rows whose violations differ from replay: %d" % n_row_mismatch)
    if n_multi and n_row_mismatch == 0:
        print("=> 重复发生在行写入之后，jsonl 的行没有被污染，结论可用")
    elif n_row_mismatch:
        print("=> 有行的计数是两遍事件混算的结果，该文件的 violations/blocked 不可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
