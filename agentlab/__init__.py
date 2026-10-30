"""agentlab: a replayable substrate for long-running agent state-safety research.

Components map to section 5 and section 14 of the research plan:

  schema    -- the provenance tuple recorded for every state change
  store     -- append-only event log, blobs, replay and diff
  policy    -- the rule set and its enforcement
  tools     -- filesystem / SQLite / local-network tools with resource effects
  broker    -- the only path from model intent to resource effect
  context   -- long-context management and the four compaction strategies
  memory    -- long-term memory with provenance and dependency revocation
  skills    -- frozen skill packages with review-hash binding
  pollute   -- four-entry-point pollution injector
  tasks     -- twelve base tasks in two legitimate work domains
  agent     -- the episode loop
  metrics   -- rule retention, violation, utility
"""

from .schema import Authority, Decision, Event, Kind, Lifetime, Rule, Transform, Verification
from .store import EventStore, Trace, verify_determinism
from .policy import Policy, norm_path, path_matches
from .tools import Tools, Workspace, ToolResult, TOOL_SPECS, tools_prompt
from .broker import ToolBroker
from .context import ContextManager, STRATEGIES
from .memory import MemoryStore, MemoryItem
from .skills import Skill, SkillLoader, default_skills
from .pollute import Injector, Injection, PAYLOADS, PAYLOADS_ALIGNED, PAYLOAD_SETS, POINTS, classify_effect
from .tasks import Task, TASKS, TASK_BY_ID, build_workspace, all_tasks
from .agent import Episode, EpisodeResult, parse_tool_call
from .metrics import judge_rule_recall, retention_rate, aggregate, format_table, harness_retention
from .judge import judge_deterministic, cohen_kappa, explain as judge_explain, RULE_ELEMENTS
from .llm import LLMClient, MockLLM, TokenizerCounter, token_count_heuristic

__all__ = [
    "Authority", "Decision", "Event", "Kind", "Lifetime", "Rule", "Transform", "Verification",
    "EventStore", "Trace", "verify_determinism",
    "Policy", "norm_path", "path_matches",
    "Tools", "Workspace", "ToolResult", "TOOL_SPECS", "tools_prompt",
    "ToolBroker",
    "ContextManager", "STRATEGIES",
    "MemoryStore", "MemoryItem",
    "Skill", "SkillLoader", "default_skills",
    "Injector", "Injection", "PAYLOADS", "PAYLOADS_ALIGNED", "PAYLOAD_SETS", "POINTS", "classify_effect",
    "Task", "TASKS", "TASK_BY_ID", "build_workspace", "all_tasks",
    "Episode", "EpisodeResult", "parse_tool_call",
    "judge_rule_recall", "retention_rate", "aggregate", "format_table", "harness_retention",
    "judge_deterministic", "cohen_kappa", "judge_explain", "RULE_ELEMENTS",
    "LLMClient", "MockLLM", "TokenizerCounter", "token_count_heuristic",
]
