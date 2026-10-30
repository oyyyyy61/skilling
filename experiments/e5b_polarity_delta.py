"""Measure what negation-awareness actually changes on the stored probes.

The element groups already require a prohibitive word, so the polarity check
may be redundant in practice. Rather than assert either way, re-score every
probe in the E1b store with polarity on and off and report the delta.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import EventStore, Policy, judge_deterministic, retention_rate  # noqa: E402

STORE = "/root/autodl-tmp/work/lab/results/store_e1b_full"
RULE_IDS = [r.id for r in Policy.standard().active_rules()]


def main() -> int:
    store = EventStore(STORE)
    sessions = store.sessions()
    ons, offs, diffs = [], [], []
    n = 0
    for sid in sessions:
        trace = store.replay(sid)
        probe = ""
        for e in trace.events:
            if str(getattr(e.kind, "value", e.kind)) == "probe" and e.content:
                probe = e.content
        if not probe.strip():
            continue
        n += 1
        on = judge_deterministic(RULE_IDS, probe, polarity=True)
        off = judge_deterministic(RULE_IDS, probe, polarity=False)
        ons.append(retention_rate(on))
        offs.append(retention_rate(off))
        if on != off:
            diffs.append((sid, probe[:120], {k: (off[k], on[k]) for k in off if off[k] != on[k]}))
    print("episodes with probe: %d" % n)
    if n:
        print("mean retention  polarity-off: %.4f" % (sum(offs) / n))
        print("mean retention  polarity-on : %.4f" % (sum(ons) / n))
    print("episodes where scoring changed: %d" % len(diffs))
    for sid, text, d in diffs[:10]:
        print("  %s %s | %s" % (sid[:18], d, text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
