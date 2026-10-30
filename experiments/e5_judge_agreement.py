"""E5: 独立判分器 —— 机械判分 vs 同模型自评的一致性

规则保持率此前由产出答案的同一个 7B 模型打分（自评）。本实验用事件库里
已存的探针原文，让一个**确定性判分器**重新打分，然后比较两者。

不新跑模型，只重放事件 + 重新判分，所以没有采样噪声：
两边的分歧完全来自判分口径，而不是模型抖动。

输出：
  每条规则的判定一致率、Cohen's kappa、分歧样本（含缺了哪个要素）

用法：
  python experiments/e5_judge_agreement.py --store results/store_e1b_full \
      --jsonl results/e1b_e1b_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from agentlab import (  # noqa: E402
    EventStore, Kind, Policy, cohen_kappa, judge_deterministic, judge_explain,
)


def extract_probe(trace) -> str:
    """The probe answer is recorded as a PROBE event at the end of the episode."""
    want = Kind.PROBE.value if hasattr(Kind.PROBE, "value") else str(Kind.PROBE)
    for ev in reversed(trace.events):
        got = getattr(ev.kind, "value", ev.kind)
        if got == want:
            return ev.content or ""
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default="e5_judge")
    ap.add_argument("--max-examples", type=int, default=8)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    store = EventStore(args.store)
    rule_ids = [r.id for r in Policy.standard().active_rules()]

    pairs = []          # (llm_verdict, det_verdict)
    per_rule = {rid: Counter() for rid in rule_ids}
    examples = []
    missing_probe = 0
    used = 0
    # stratified records: (probe_len, strategy, llm_true_count, det_true_count, len(rule_ids))
    strata = []

    for row in rows:
        sid = row.get("session")
        if not sid:
            continue
        try:
            trace = store.replay(sid)
        except Exception:  # noqa: BLE001
            continue
        probe = extract_probe(trace)
        if not probe:
            missing_probe += 1
            continue
        used += 1
        det = judge_deterministic(rule_ids, probe)
        llm = row.get("retention_detail") or {}
        strata.append((len(probe), row.get("strategy") or "?",
                       sum(1 for rid in rule_ids if llm.get(rid)),
                       sum(1 for rid in rule_ids if det.get(rid)),
                       len(rule_ids), sid,
                       (row.get("strategy") or "?", row.get("compact_every"))))
        for rid in rule_ids:
            a = bool(llm.get(rid))
            b = bool(det.get(rid))
            pairs.append((a, b))
            per_rule[rid][("agree" if a == b else "differ")] += 1
            if a != b and len(examples) < args.max_examples:
                examples.append({
                    "session": sid,
                    "strategy": row.get("strategy"),
                    "compact_every": row.get("compact_every"),
                    "rule": rid,
                    "llm_says": a,
                    "det_says": b,
                    "missing_elements": judge_explain([rid], probe).get(rid),
                    "probe_head": probe[:400],
                })

    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    kappa = cohen_kappa(pairs)
    llm_pos = sum(1 for a, _ in pairs if a)
    det_pos = sum(1 for _, b in pairs if b)

    def w(x):
        return "%.3f" % x

    print("episodes replayed with probe: %d (missing probe: %d)" % (used, missing_probe))
    print("judgements compared: %d" % n)
    print("overall agreement: %s   cohen kappa: %s" % (w(agree / n if n else 0), w(kappa)))
    print("llm judge recalls: %d (%.1f%%)   deterministic recalls: %d (%.1f%%)"
          % (llm_pos, 100.0 * llm_pos / n if n else 0, det_pos, 100.0 * det_pos / n if n else 0))
    print()

    # second pass: per-rule true counts (llm vs deterministic)
    per_rule_out = {rid: {"agree": per_rule[rid]["agree"],
                          "differ": per_rule[rid]["differ"],
                          "n": per_rule[rid]["agree"] + per_rule[rid]["differ"],
                          "llm_true": 0, "det_true": 0} for rid in rule_ids}
    for row in rows:
        sid = row.get("session")
        if not sid:
            continue
        try:
            trace = store.replay(sid)
        except Exception:  # noqa: BLE001
            continue
        probe = extract_probe(trace)
        if not probe:
            continue
        det = judge_deterministic(rule_ids, probe)
        llm = row.get("retention_detail") or {}
        for rid in rule_ids:
            per_rule_out[rid]["llm_true"] += 1 if llm.get(rid) else 0
            per_rule_out[rid]["det_true"] += 1 if det.get(rid) else 0

    header = "rule  n     agree_rate  llm_true  det_true  llm%   det%"
    print(header)
    print("-" * len(header))
    for rid in rule_ids:
        o = per_rule_out[rid]
        tot = o["n"] or 1
        o["agree_rate"] = round(o["agree"] / tot, 3)
        print("%-5s %-5d %-11s %-9d %-9d %-6.1f %-6.1f"
              % (rid, o["n"], w(o["agree_rate"]), o["llm_true"], o["det_true"],
                 100.0 * o["llm_true"] / tot, 100.0 * o["det_true"] / tot))

    # ---- stratification: does judge agreement depend on answer informativeness?
    buckets = [("<40", 0, 40), ("40-100", 40, 100), ("100-300", 100, 300), ("300+", 300, 10 ** 9)]
    print("\n## agreement by probe length (chars)")
    hdr = "bucket    episodes  llm_recall%  det_recall%  gap(pp)  llm_only_true  det_only_true"
    print(hdr)
    print("-" * len(hdr))
    strat_out = {}
    for label, lo, hi in buckets:
        items = [s for s in strata if lo <= s[0] < hi]
        if not items:
            continue
        n_ep = len(items)
        tot_r = sum(s[4] for s in items)
        llm_t = sum(s[2] for s in items)
        det_t = sum(s[3] for s in items)
        # per-judgement counts of one-sided verdicts
        llm_only = det_only = 0
        for row in rows:
            sid = row.get("session")
            rec = next((s for s in items if s[5] == sid), None)
            if rec is None:
                continue
            try:
                trace = store.replay(sid)
            except Exception:  # noqa: BLE001
                continue
            probe = extract_probe(trace)
            det = judge_deterministic(rule_ids, probe)
            llm = row.get("retention_detail") or {}
            for rid in rule_ids:
                if llm.get(rid) and not det.get(rid):
                    llm_only += 1
                elif det.get(rid) and not llm.get(rid):
                    det_only += 1
        llm_pct = 100.0 * llm_t / tot_r if tot_r else 0
        det_pct = 100.0 * det_t / tot_r if tot_r else 0
        strat_out[label] = {"episodes": n_ep, "llm_recall": round(llm_pct, 1),
                            "det_recall": round(det_pct, 1),
                            "llm_only_true": llm_only, "det_only_true": det_only}
        print("%-9s %-9d %-12.1f %-12.1f %-8.1f %-14d %d"
              % (label, n_ep, llm_pct, det_pct, llm_pct - det_pct, llm_only, det_only))

    print("\n## agreement by strategy")
    hdr2 = "strategy                 episodes  llm_recall%  det_recall%  gap(pp)"
    print(hdr2)
    print("-" * len(hdr2))
    by_strat = {}
    for s in strata:
        by_strat.setdefault(s[1], []).append(s)
    strat_out_strategy = {}
    for name in sorted(by_strat):
        items = by_strat[name]
        tot_r = sum(s[4] for s in items)
        llm_pct = 100.0 * sum(s[2] for s in items) / tot_r if tot_r else 0
        det_pct = 100.0 * sum(s[3] for s in items) / tot_r if tot_r else 0
        strat_out_strategy[name] = {"episodes": len(items), "llm_recall": round(llm_pct, 1),
                                    "det_recall": round(det_pct, 1)}
        print("%-24s %-9d %-12.1f %-12.1f %.1f"
              % (name, len(items), llm_pct, det_pct, llm_pct - det_pct))

    # ---- does the E1b dose-response survive the independent judge?
    print("\n## dose-response under both judges (E1b cells)")
    hdr3 = "strategy                 K    episodes  llm_recall%  det_recall%  delta(pp)"
    print(hdr3)
    print("-" * len(hdr3))
    cells_out = {}
    by_cell = {}
    for s in strata:
        by_cell.setdefault(s[6], []).append(s)
    for key in sorted(by_cell, key=lambda k: (str(k[0]), -1 if k[1] is None else k[1])):
        items = by_cell[key]
        tot_r = sum(s[4] for s in items)
        llm_pct = 100.0 * sum(s[2] for s in items) / tot_r if tot_r else 0
        det_pct = 100.0 * sum(s[3] for s in items) / tot_r if tot_r else 0
        label = "%s|%s" % key
        cells_out[label] = {"episodes": len(items), "llm_recall": round(llm_pct, 1),
                            "det_recall": round(det_pct, 1)}
        print("%-24s %-4s %-9d %-12.1f %-12.1f %.1f"
              % (key[0], key[1], len(items), llm_pct, det_pct, llm_pct - det_pct))

    if examples:
        print("\n## disagreement examples")
        for e in examples:
            print("\n[%s] %s k=%s rule=%s llm=%s det=%s missing=%s"
                  % (e["strategy"], e["session"], e["compact_every"], e["rule"],
                     e["llm_says"], e["det_says"], e["missing_elements"]))
            print("   " + e["probe_head"].replace("\n", " ")[:300])

    os.makedirs(os.path.join(os.path.dirname(_HERE), args.out), exist_ok=True)
    outp = os.path.join(os.path.dirname(_HERE), args.out, "%s.json" % args.tag)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({
            "episodes": used,
            "judgements": n,
            "agreement": round(agree / n, 3) if n else None,
            "kappa": round(kappa, 3),
            "llm_positive": llm_pos,
            "det_positive": det_pos,
            "per_rule": per_rule_out,
            "stratified_by_length": strat_out,
            "stratified_by_strategy": strat_out_strategy,
            "dose_response_cells": cells_out,
            "examples": examples,
        }, f, ensure_ascii=False, indent=2)
    print("\nwrote %s" % outp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
