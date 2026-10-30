"""E6 危害类型分解：为什么 B3/B4 的危害率全是 1.00？

救援脚本重建出的表里，B3/B4 六个载体全是 0.8–1.0，看不出载体效应。
两种可能：
  (a) 这两个任务本身就会触发危害动作，载体无关（天花板效应，任务对该指标无效）
  (b) 判定器把某个良性动作算成了危害

这个脚本按任务 × 载体统计每一类危害出现的次数，直接看出来是哪种。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore  # noqa: E402
from agentlab.pollute import classify_effect  # noqa: E402

SESS_RE = re.compile(r"^sess_(?P<task>[^_]+)_[^_]+_[^_]+_(?P<tag>.*)$")
TAG_RE = re.compile(r"_r(?P<rep>\d+)_(?P<label>.+)$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    args = ap.parse_args()

    store = EventStore(args.store)
    per_task = defaultdict(Counter)
    per_cell = defaultdict(Counter)
    for sid in store.sessions():
        m = SESS_RE.match(sid)
        if not m:
            continue
        task = m.group("task")
        t = TAG_RE.search(m.group("tag"))
        if not t:
            continue
        label = t.group("label")
        seen = set()
        for tc in store.replay(sid).tool_calls:
            c = classify_effect(tc.effect or {})
            if c in ("none", "benign", "blocked"):
                continue
            seen.add(c)
            per_task[task][c] += 1
            per_cell[(task, label)][c] += 1
        per_task[task]["_sessions"] += 0
        per_task[task]["_n"] += 0

    # 每个 session 至少出现一次某类危害
    sess_level = defaultdict(Counter)
    for sid in store.sessions():
        m = SESS_RE.match(sid)
        if not m:
            continue
        task = m.group("task")
        t = TAG_RE.search(m.group("tag"))
        if not t:
            continue
        labels = set()
        for tc in store.replay(sid).tool_calls:
            c = classify_effect(tc.effect or {})
            if c in ("none", "benign", "blocked"):
                continue
            labels.add(c)
        sess_level[task]["_sessions"] += 1
        for c in labels:
            sess_level[task][c] += 1

    print("任务  session数  各类危害的 session 占比")
    for task in sorted(sess_level):
        row = sess_level[task]
        n = row["_sessions"]
        parts = ["%s=%.2f" % (k, v / n) for k, v in sorted(row.items()) if k != "_sessions"]
        print("  %-3s %3d      %s" % (task, n, "  ".join(parts)))

    print("\n任务/载体  危害类型计数（同一 session 内按类型去重累加）")
    for (task, label) in sorted(per_cell):
        c = per_cell[(task, label)]
        print("  %-3s %-8s %s" % (task, label, dict(c)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
