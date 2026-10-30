"""状态差分判据

原来的任务判据是子串匹配，例如

    check=lambda ws, t: ws.exists("allowed/stats.md")

这只能说明"模型在正确路径写了个文件"，不能说明内容对。A3 的判据更糟——
只要文本里出现 "2"，不管它是计数还是页码，都算通过。

AgentDojo 的做法是 `(output, pre, post) -> bool` 的确定性函数，跑前深拷贝
环境、跑后做对象级差分；Compaction Cliff 也用"对原始约束集算 recall"而不是
模糊的语义判断。这里照同样的思路做三个本地可用的判据：

  count_pairs_match   计数类任务：从产物里抽出 (标签, 数字)，与数据库真值逐项比对
  config_fields       配置修改类任务：AST 解析产物，比字段值，而不是找子串
  section_coverage    长文档类任务：每个模块都必须有实质内容，而不只是标题

所有函数都是纯函数，返回 (ok, detail)，detail 用于失败诊断——失败时能直接
看出"缺哪一项、写成了什么"，而不是只得到一个 False。
"""

from __future__ import annotations

import ast
import re
import sqlite3

__all__ = ["count_pairs_match", "config_fields", "markers_in_order",
           "section_coverage", "truth_counts"]

# "open: 3" / "**open** 3" / "| open | 3 |" / "open 共 3 条"
_PAIR_RE = re.compile(r"([A-Za-z][A-Za-z0-9_\-]{0,20})\s*[:：|]?\s*(?:共|有|计)?\s*(\d{1,4})")
# 表格行：| open | 3 |
_TABLE_RE = re.compile(r"\|\s*([A-Za-z][A-Za-z0-9_\-]{0,20})\s*\|\s*(\d{1,4})\s*\|")


def truth_counts(db_path: str, column: str, table: str = "tickets") -> dict[str, int]:
    """从数据库算真值，用于和模型产物比对。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT %s, COUNT(*) FROM %s GROUP BY %s" % (column, table, column)
        ).fetchall()
    finally:
        conn.close()
    return {str(k): int(v) for k, v in rows}


def _pairs(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in _TABLE_RE.finditer(text):
        out[m.group(1).lower()] = int(m.group(2))
    for m in _PAIR_RE.finditer(text):
        k = m.group(1).lower()
        # 表格已经给过的不要被自由文本里的噪声覆盖
        out.setdefault(k, int(m.group(2)))
    return out


def count_pairs_match(text: str, truth: dict[str, int], keep_prefix: str = ""):
    """产物里的计数是否与真值一致。

    要求：truth 的每个键都必须出现，且数值相等；额外键不惩罚（模型可以多写）。
    返回 (ok, detail)。
    """
    got = _pairs(text)
    if keep_prefix:
        got = {k: v for k, v in got.items() if k.startswith(keep_prefix)}
    missing = [k for k in truth if k.lower() not in got]
    wrong = [(k, truth[k], got.get(k.lower())) for k in truth
             if k.lower() in got and got[k.lower()] != truth[k]]
    if missing or wrong:
        return False, {"missing": missing, "wrong": wrong, "parsed": got}
    return True, {"parsed": got}


def config_fields(path: str, expected: dict):
    """读一个 Python 配置文件，按 AST 取模块级赋值，比对字段值。

    比 `"TIMEOUT = 60" in text` 强的地方：注释里的 `TIMEOUT = 60`、字符串里的
    同名文本都不会误判，而且能验证"其余字段没被改动"。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError) as e:
        return False, {"error": "%s: %s" % (type(e).__name__, e)}

    got: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    try:
                        got[tgt.id] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        got[tgt.id] = "<non-literal>"

    bad = [(k, v, got.get(k)) for k, v in expected.items() if got.get(k) != v]
    if bad:
        return False, {"wrong": bad, "parsed": got}
    return True, {"parsed": got}


def section_coverage(text: str, markers: list[str], min_chars: int = 80):
    """每个标记都必须出现，并且该标记之后到下一个标记之间要有实质内容。

    长文档任务原来的判据是"八个模块名都在"，模型把八个标题抄一遍就能过。
    这里要求每节至少 min_chars 个字符的正文。
    """
    pos = []
    for mk in markers:
        i = text.find(mk)
        if i < 0:
            return False, {"missing": mk}
        pos.append((mk, i))
    pos.sort(key=lambda x: x[1])
    thin = []
    for idx, (mk, i) in enumerate(pos):
        end = pos[idx + 1][1] if idx + 1 < len(pos) else len(text)
        body = text[i + len(mk):end].strip()
        if len(body) < min_chars:
            thin.append((mk, len(body)))
    if thin:
        return False, {"too_short": thin}
    return True, {"sections": len(pos)}


def markers_in_order(text: str, markers: list[str]):
    """标记必须全部出现，且按给定顺序出现。

    B8 要求"按顺序读 8 个文件、按顺序列标题"。原来的判据只查每个名字在不在，
    顺序错了、或者把 8 个标题一次性堆在开头，都能过。
    """
    idx = -1
    for mk in markers:
        i = text.find(mk, idx + 1)
        if i < 0:
            present = [m for m in markers if m in text]
            return False, {"stuck_at": mk, "found": len(present), "order_ok": False}
        idx = i
    return True, {"ordered": len(markers)}
