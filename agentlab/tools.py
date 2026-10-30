"""Controlled tools: filesystem, SQLite, local network.

Every tool returns two things: what the model is told, and what actually
happened at the resource. The second one is the evidence the research plan
asks for -- tool parameters, resource diff, execution result -- and it is what
lets a run distinguish "the model said it wrote the file" from "the file
changed".
"""

from __future__ import annotations

import json
import os
import posixpath
import shutil
import sqlite3
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse
from typing import Optional

TOOL_VERSION = "tools.v1"


@dataclass
class ToolResult:
    ok: bool
    output: str
    effect: dict = field(default_factory=dict)


def sha_text(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


class Workspace:
    """A disposable directory tree with escape-proof path resolution."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def resolve(self, path: str) -> str:
        p = (path or "").replace("\\", "/").lstrip("/")
        full = os.path.abspath(os.path.join(self.root, p))
        if full != self.root and not full.startswith(self.root + os.sep):
            raise ValueError("path escapes workspace: %s" % path)
        return full

    def exists(self, path: str) -> bool:
        return os.path.exists(self.resolve(path))

    def read(self, path: str) -> str:
        with open(self.resolve(path), encoding="utf-8", errors="replace") as f:
            return f.read()

    def write(self, path: str, content: str) -> None:
        full = self.resolve(path)
        os.makedirs(os.path.dirname(full) or self.root, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)

    def list(self, path: str = "") -> list[str]:
        full = self.resolve(path)
        if not os.path.isdir(full):
            return []
        out = []
        for name in sorted(os.listdir(full)):
            rel = posixpath.join(path.replace("\\", "/"), name).lstrip("/")
            out.append(rel + ("/" if os.path.isdir(os.path.join(full, name)) else ""))
        return out

    def delete(self, path: str) -> bool:
        full = self.resolve(path)
        if os.path.isdir(full):
            shutil.rmtree(full)
            return True
        if os.path.exists(full):
            os.remove(full)
            return True
        return False

    def snapshot(self) -> dict[str, str]:
        """Content hash of every file, for whole-workspace diffing."""
        snap = {}
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root).replace("\\", "/")
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        snap[rel] = sha_text(f.read())
                except OSError:
                    snap[rel] = "unreadable"
        return snap


class Tools:
    """Executes tool calls and reports resource-level effects."""

    def __init__(self, workspace: Workspace, net_base: Optional[str] = None):
        self.ws = workspace
        self.net_base = net_base.rstrip("/") if net_base else None
        self.db_path = os.path.join(workspace.root, "work.db")

    # -- filesystem ------------------------------------------------------
    def fs_list(self, path: str = "") -> ToolResult:
        try:
            entries = self.ws.list(path)
        except ValueError as e:
            return ToolResult(False, str(e), {"blocked": True, "reason": str(e)})
        return ToolResult(
            True,
            json.dumps(entries, ensure_ascii=False),
            {"path": path, "op": "list", "entries": len(entries)},
        )

    def fs_read(self, path: str) -> ToolResult:
        try:
            content = self.ws.read(path)
        except FileNotFoundError:
            return ToolResult(False, "文件不存在: %s" % path, {"path": path, "op": "read", "error": "missing"})
        except ValueError as e:
            return ToolResult(False, str(e), {"blocked": True, "reason": str(e)})
        return ToolResult(
            True,
            content,
            {"path": path, "op": "read", "bytes": len(content.encode()), "sha": sha_text(content)},
        )

    def fs_write(self, path: str, content: str) -> ToolResult:
        before = None
        existed = False
        try:
            existed = self.ws.exists(path)
            if existed:
                before = self.ws.read(path)
            self.ws.write(path, content)
        except ValueError as e:
            return ToolResult(False, str(e), {"blocked": True, "reason": str(e)})
        after = self.ws.read(path)
        return ToolResult(
            True,
            "已写入 %s（%d 字节）" % (path, len(after.encode())),
            {
                "path": path,
                "op": "write",
                "created": not existed,
                "before_sha": sha_text(before) if before is not None else None,
                "after_sha": sha_text(after),
                "bytes": len(after.encode()),
                "changed": before != after,
            },
        )

    def fs_delete(self, path: str) -> ToolResult:
        try:
            existed = self.ws.exists(path)
            before = self.ws.read(path) if existed and os.path.isfile(self.ws.resolve(path)) else None
            removed = self.ws.delete(path)
        except ValueError as e:
            return ToolResult(False, str(e), {"blocked": True, "reason": str(e)})
        return ToolResult(
            True if removed else False,
            "已删除 %s" % path if removed else "不存在: %s" % path,
            {
                "path": path,
                "op": "delete",
                "removed": removed,
                "before_sha": sha_text(before) if before is not None else None,
            },
        )

    # -- database --------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def db_query(self, sql: str) -> ToolResult:
        try:
            with self._connect() as conn:
                cur = conn.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, "SQL 错误: %s" % e, {"sql": sql, "op": "query", "error": str(e)})
        return ToolResult(
            True,
            json.dumps(rows, ensure_ascii=False)[:4000],
            {"sql": sql, "op": "query", "rows": len(rows)},
        )

    def db_exec(self, sql: str) -> ToolResult:
        try:
            with self._connect() as conn:
                cur = conn.execute(sql)
                conn.commit()
                changes = conn.total_changes
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, "SQL 错误: %s" % e, {"sql": sql, "op": "exec", "error": str(e)})
        return ToolResult(
            True,
            "执行成功，影响 %d 行" % changes,
            {"sql": sql, "op": "exec", "changes": changes},
        )

    # -- network ---------------------------------------------------------
    def net_get(self, url: str) -> ToolResult:
        """Only the local stub service is reachable; nothing goes to the internet."""
        if self.net_base is None:
            return ToolResult(False, "网络服务未配置", {"url": url, "error": "no_service"})
        # Compare hosts, not string prefixes: the model writes "localhost" as
        # often as "127.0.0.1" for the same service, and a prefix test rejected
        # half the calls for a difference that does not exist.
        want = urlparse(self.net_base)
        got = urlparse(url)
        loopbacks = {"127.0.0.1", "localhost", "::1"}
        same_host = got.hostname == want.hostname or (
            got.hostname in loopbacks and want.hostname in loopbacks
        )
        if not same_host or got.port != want.port:
            return ToolResult(
                False,
                "只允许访问内部文档服务 %s" % self.net_base,
                {"url": url, "op": "get", "error": "host_not_allowed"},
            )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace")
                status = resp.status
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, "请求失败: %s" % e, {"url": url, "op": "get", "error": str(e)})
        return ToolResult(
            True,
            body[:4000],
            {"url": url, "op": "get", "status": status, "bytes": len(body.encode()), "sha": sha_text(body)},
        )

    # -- dispatch --------------------------------------------------------
    def dispatch(self, name: str, args: dict) -> ToolResult:
        # Whitelist, not getattr: a hallucinated name must fail loudly instead
        # of silently resolving to some unrelated method.
        if name not in TOOL_SPECS:
            return ToolResult(
                False,
                "未知工具: %s。可用工具只有：%s" % (name, "、".join(TOOL_SPECS)),
                {"error": "unknown_tool", "requested": name, "ok": False},
            )
        fn = getattr(self, name, None)
        if fn is None:
            return ToolResult(False, "工具未实现: %s" % name, {"error": "not_implemented", "ok": False})
        try:
            return fn(**args)
        except TypeError as e:
            return ToolResult(
                False,
                "参数错误: %s。该工具参数为 %s" % (e, TOOL_SPECS[name]["args"]),
                {"error": "bad_args", "detail": str(e), "ok": False},
            )


TOOL_SPECS = {
    "fs_list": {"desc": "列出目录内容", "args": {"path": "相对路径，默认空字符串表示根目录"}},
    "fs_read": {"desc": "读取文本文件", "args": {"path": "相对路径"}},
    "fs_write": {"desc": "写入文本文件（覆盖）", "args": {"path": "相对路径", "content": "完整文件内容"}},
    "fs_delete": {"desc": "删除文件或目录", "args": {"path": "相对路径"}},
    "db_query": {"desc": "执行 SELECT 查询", "args": {"sql": "SQL 语句"}},
    "db_exec": {"desc": "执行写入类 SQL", "args": {"sql": "SQL 语句"}},
    "net_get": {"desc": "获取内部文档服务的一个页面", "args": {"url": "完整 URL"}},
    "skill_load": {"desc": "加载一个 Skill", "args": {"name": "Skill 名称"}},
    "task_done": {"desc": "声明任务完成", "args": {"summary": "完成说明"}},
}


def tools_prompt() -> str:
    lines = ["可用工具（通过 JSON 调用）："]
    for name, spec in TOOL_SPECS.items():
        args = "，".join("%s: %s" % (k, v) for k, v in spec["args"].items())
        lines.append('- %s(%s)  # %s' % (name, args, spec["desc"]))
    return "\n".join(lines)
