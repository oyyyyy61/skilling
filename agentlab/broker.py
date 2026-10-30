"""Tool broker: policy gate + execution + evidence recording.

The broker is the only path from model intent to resource effect. In
`enforced` mode a rule violation is blocked and recorded; in `open` mode (the
no-defence baseline) the same call executes, which is how the experiment gets
a denominator for "what the violation would have done".
"""

from __future__ import annotations

from typing import Optional

from .policy import Policy
from .schema import Decision, Event, Kind, Lifetime, Transform, Verification
from .store import EventStore
from .tools import TOOL_VERSION, ToolResult, Tools


class ToolBroker:
    def __init__(
        self,
        policy: Policy,
        tools: Tools,
        store: EventStore,
        task_id: str,
        session_id: str,
        mode: str = "enforced",
        skill_loader=None,
        model_version: Optional[str] = None,
    ):
        self.policy = policy
        self.tools = tools
        self.store = store
        self.task_id = task_id
        self.session_id = session_id
        self.mode = mode  # enforced | open
        self.skill_loader = skill_loader
        self.model_version = model_version
        self.n_calls = 0

    def call(self, name: str, args: dict) -> tuple[ToolResult, Decision]:
        self.n_calls += 1

        if self.mode == "open":
            decision = Decision(allow=True, reason="open mode: no policy enforcement")
        else:
            decision = self.policy.check(name, args, tool_calls_so_far=self.n_calls - 1)

        if not decision.allow:
            result = ToolResult(
                False,
                "调用被拒绝：%s" % decision.reason,
                {
                    "blocked": True,
                    "violation": decision.violation,
                    "needs_approval": decision.needs_approval,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                    "attempted": {name: args},
                },
            )
            self._record(name, args, result, "denied", decision, Verification.UNVERIFIED)
            return result, decision

        if name == "skill_load" and self.skill_loader is not None:
            result = self.skill_loader.load(args.get("name", ""))
        else:
            result = self.tools.dispatch(name, args)

        self._record(name, args, result, "allowed", decision, Verification.VERIFIED)
        return result, decision

    def _record(
        self,
        name: str,
        args: dict,
        result: ToolResult,
        authorization: str,
        decision: Decision,
        status: str,
    ) -> Event:
        ev = Event(
            kind=Kind.TOOL_CALL,
            task_id=self.task_id,
            session_id=self.session_id,
            authority="system_rule" if authorization == "allowed" else "model_inference",
            transformation=Transform.INGEST,
            authorization=authorization,
            verification_status=status,
            tool_version=TOOL_VERSION,
            model_version=self.model_version,
            tool_call={"name": name, "args": args},
            effect=result.effect,
            evidence={"output_preview": result.output[:400]},
            extra={
                "rule_id": decision.rule_id,
                "reason": decision.reason,
                "needs_approval": decision.needs_approval,
                "allowed": decision.allow,
            },
        )
        return self.store.append(ev)
