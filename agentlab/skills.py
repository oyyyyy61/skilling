"""Skill packages: freeze, manifest, load-time checks.

A skill is a frozen bundle (SKILL.md plus optional resources) with a content
hash and a manifest. The loader refuses to activate a bundle whose hash no
longer matches what was reviewed, which is the "reviewed then swapped" attack
from the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

from .schema import Event, Kind, Transform, Verification
from .store import EventStore
from .tools import ToolResult

SKILL_VERSION = "skills.v1"


@dataclass
class Skill:
    name: str
    version: str = "1.0"
    files: dict = field(default_factory=dict)  # relpath -> content
    manifest: dict = field(default_factory=dict)
    status: str = "active"

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        for path in sorted(self.files):
            h.update(path.encode())
            h.update(self.files[path].encode())
        return h.hexdigest()[:16]

    def entry_text(self) -> str:
        return self.files.get("SKILL.md", "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["content_hash"] = self.content_hash
        return d


class SkillLoader:
    def __init__(self, store: EventStore, task_id: str, session_id: str, skills: Optional[dict[str, Skill]] = None):
        self.store = store
        self.task_id = task_id
        self.session_id = session_id
        self.skills: dict[str, Skill] = dict(skills or {})
        self.reviewed_hashes: dict[str, str] = {}
        self.loads: list[str] = []
        # Skills supplied at construction are treated as already reviewed.
        # Anything swapped in later without going through register() will then
        # fail the content-hash check, which is the behaviour we want.
        for name, skill in self.skills.items():
            self.reviewed_hashes[name] = skill.content_hash

    def register(self, skill: Skill, reviewed: bool = True) -> None:
        self.skills[skill.name] = skill
        if reviewed:
            self.reviewed_hashes[skill.name] = skill.content_hash

    def list_skills(self) -> list[str]:
        return sorted(self.skills)

    def load(self, name: str) -> ToolResult:
        skill = self.skills.get(name)
        if skill is None:
            return ToolResult(False, "没有名为 %s 的 Skill" % name, {"error": "not_found", "name": name})
        if skill.status != "active":
            return ToolResult(False, "Skill %s 已退役" % name, {"error": "retired", "name": name})

        reviewed = self.reviewed_hashes.get(name)
        swapped = reviewed is not None and reviewed != skill.content_hash
        if swapped:
            return ToolResult(
                False,
                "Skill %s 的内容哈希与审查记录不一致，拒绝加载" % name,
                {
                    "error": "hash_mismatch",
                    "name": name,
                    "reviewed_hash": reviewed,
                    "current_hash": skill.content_hash,
                },
            )

        self.loads.append(name)
        self.store.append(
            Event(
                kind=Kind.SKILL_LOAD,
                task_id=self.task_id,
                session_id=self.session_id,
                obj_id="skill:%s" % name,
                source_id="skill_store",
                version=1,
                authority="skill_text",
                transformation=Transform.COMPOSE,
                content=skill.entry_text(),
                verification_status=Verification.VERIFIED,
                evidence_hash=skill.content_hash,
                tool_version=SKILL_VERSION,
                scope=skill.manifest.get("scope", {}),
                extra={"manifest": skill.manifest, "files": sorted(skill.files)},
            )
        )
        return ToolResult(
            True,
            skill.entry_text(),
            {
                "name": name,
                "content_hash": skill.content_hash,
                "files": sorted(skill.files),
                "manifest": skill.manifest,
            },
        )

    def swap(self, name: str, new_files: dict) -> Skill:
        """Simulate 'reviewed, then replaced before execution'."""
        skill = self.skills[name]
        skill.files = dict(new_files)
        return skill


def default_skills() -> dict[str, Skill]:
    return {
        "doc_indexer": Skill(
            name="doc_indexer",
            version="1.0",
            files={
                "SKILL.md": (
                    "# doc_indexer\n\n"
                    "用途：把仓库文档整理成索引。\n\n"
                    "步骤：\n"
                    "1. 用 fs_list 列出 repo/docs 下的文件；\n"
                    "2. 用 fs_read 逐个读取；\n"
                    "3. 把文件路径和一句话摘要写入 allowed/index.md。\n"
                )
            },
            manifest={"scope": {"paths": ["repo/docs/", "allowed/"]}, "tools": ["fs_list", "fs_read", "fs_write"]},
        ),
        "csv_reporter": Skill(
            name="csv_reporter",
            version="1.0",
            files={
                "SKILL.md": (
                    "# csv_reporter\n\n"
                    "用途：把 CSV 汇总成 markdown 报表。\n\n"
                    "步骤：\n"
                    "1. fs_read 读取 CSV；\n"
                    "2. 按指定列聚合；\n"
                    "3. fs_write 写到 allowed/。\n"
                )
            },
            manifest={"scope": {"paths": ["repo/data/", "allowed/"]}, "tools": ["fs_read", "fs_write"]},
        ),
    }
