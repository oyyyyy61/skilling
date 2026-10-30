"""Calibration: find a token budget that actually triggers compaction.

Runs one task at several budgets and reports turns, compactions and prompt
size, so E1's manipulation is known to fire before the full sweep is run.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import Episode, EventStore, LLMClient, Policy, TASK_BY_ID  # noqa: E402
from agentlab.context import ContextManager  # noqa: E402


def main() -> int:
    task_id = sys.argv[1] if len(sys.argv) > 1 else "A4"
    budgets = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["500", "700", "900", "1200"])]
    llm = LLMClient(base_url="http://127.0.0.1:8000/v1", model="qwen2.5-7b", temperature=0.0, max_tokens=512)
    base = "/root/autodl-tmp/work/lab/results/calib"
    os.makedirs(base, exist_ok=True)

    for budget in budgets:
        store = EventStore(os.path.join(base, "store_%d" % budget))
        ep = Episode(
            task=TASK_BY_ID[task_id],
            policy=Policy.standard(),
            llm=llm,
            store=store,
            root=os.path.join(base, "ws_%d" % budget),
            strategy="typed_summary_protected",
            budget_tokens=budget,
            probe_at_end=True,
            tag="b%d" % budget,
        )
        res = ep.run()
        trace = store.replay(res.session_id)
        sizes = [e.extra.get("prompt_tokens_estimate") for e in trace.events if e.kind == "model_call"]
        print(
            "budget=%-5d turns=%-3d compactions=%-2d success=%-5s violation=%d prompt_sizes=%s"
            % (budget, res.turns, res.compactions, res.success, res.violations, sizes[:8]),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
