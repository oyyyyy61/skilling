"""生成 results/INDEX.md

手工维护索引一定会漏（这次就漏了 e1long 和 e7）。这个脚本扫描 results/*.jsonl，
按实验前缀分组统计 episode 数，并标注排除项。

用法：
  python experiments/make_index.py
"""

from __future__ import annotations

import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
RESULTS = os.path.join(ROOT, "results")

# 已知作废/被取代：不与结论混用
EXCLUDED = {
    "e1_e1_full.jsonl": "prompt token 计数错误时期的产物",
    "e2_e2_v1.jsonl": "早期版本",
    "e4_e4_full.jsonl": "tag 复用，事件库混入多遍",
    "e3_e3_pilot.jsonl": "早期版本",
    "e6_e6_v1.jsonl": "整批 120 个 episode 全部异常退出",
}

# 展示顺序：按实验编号，最后是杂项
ORDER = ["e1", "e1b", "e1long", "e2", "e3", "e3b", "e4", "e5", "e6", "e7", "e8", "e10", "e11", "e12", "repro"]


def prefix_of(name: str) -> str:
    base = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
    return base.split("_", 1)[0]


def count_lines(path: str) -> int:
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def main() -> int:
    files = sorted(glob.glob(os.path.join(RESULTS, "*.jsonl")))
    if not files:
        print("no jsonl in %s" % RESULTS)
        return 1

    groups: dict[str, list[tuple[str, int]]] = {}
    for p in files:
        name = os.path.basename(p)
        groups.setdefault(prefix_of(name), []).append((name, count_lines(p)))

    lines = ["# 结果索引", "",
             "由 `experiments/make_index.py` 生成，勿手工编辑。",
             "每个实验的 `.jsonl`（逐 episode 原始记录）与同名 `.md`（汇总表）。", ""]
    lines.append("**排除项**（早期版本或 tag 复用造成事件库混入多遍，不用于结论）：")
    lines.append("")
    for name, why in sorted(EXCLUDED.items()):
        lines.append("- `%s` — %s" % (name, why))
    lines.append("")

    keys = [k for k in ORDER if k in groups] + sorted(k for k in groups if k not in ORDER)
    for key in keys:
        lines.append("## %s" % key)
        lines.append("")
        lines.append("| 文件 | episodes | 备注 |")
        lines.append("|---|---|---|")
        for name, n in sorted(groups[key]):
            mark = "⚠ 已排除" if name in EXCLUDED else ""
            lines.append("| %s | %d | %s |" % (name, n, mark) if mark
                         else "| %s | %d | |" % (name, n))
        lines.append("")

    text = "\n".join(lines) + "\n"
    out = os.path.join(RESULTS, "INDEX.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s (%d files, %d groups)" % (out, len(files), len(keys)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
