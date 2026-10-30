"""E8: 换一个模型族做裁判

E5 已经证明同模型自评偏松（单边分歧 18/19 是自评说"保留"）。但 E5 的两把尺
（自评 / 机械）里，自评和被测模型是同一个模型、同一次部署，共享同一个偏好。
这里引入第三个裁判：InternLM2.5-7B-chat，与 Qwen 不同族、不同训练配方。

三方比对：
  qwen_self   从 E1b 结果里直接读到的自评判分（原实验时记录的）
  det         机械判分（要素组）
  internlm    对新模型现场提问得到的判分

同时记录 InternLM 有多少次没能返回可解析的 JSON —— 解析失败会掉进
judge_rule_recall 的词面兜底，那等于偷偷换成了另一个机械判分器，
必须单独统计而不是混进结果。

用法：
  python experiments/e8_cross_family_judge.py \
      --store results/store_e1b_full --jsonl results/e1b_e1b_full.jsonl --tag e8_v1
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
    EventStore, LLMClient, Policy, cohen_kappa, judge_deterministic,
)
from agentlab.metrics import JUDGE_PROMPT, _rules_block  # noqa: E402

import re  # noqa: E402


def extract_probe(trace) -> str:
    probe = ""
    for e in trace.events:
        if str(getattr(e.kind, "value", e.kind)) == "probe" and (e.content or "").strip():
            probe = e.content
    return probe


def ask_judge(llm, rules, answer: str):
    """Same prompt as the self-judge, but we also learn whether parsing worked."""
    ids = [r.id for r in rules]
    prompt = JUDGE_PROMPT.format(rules=_rules_block(rules), answer=answer[:3000])
    try:
        raw = llm.chat([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.0)
    except Exception:  # noqa: BLE001
        return {rid: False for rid in ids}, False
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {rid: False for rid in ids}, False
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {rid: False for rid in ids}, False
    return {rid: bool(parsed.get(rid, False)) for rid in ids}, True


def agreement(pairs):
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0
    agree = sum(1 for a, b in pairs if a == b) / n
    return agree, cohen_kappa(pairs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    ap.add_argument("--model", default="internlm2.5-7b-chat")
    ap.add_argument("--out", default="results")
    ap.add_argument("--tag", default="e8_v1")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    store = EventStore(args.store)
    rules = Policy.standard().active_rules()
    rule_ids = [r.id for r in rules]
    llm = LLMClient(base_url=args.base_url, model=args.model, temperature=0.0, max_tokens=200)

    pairs_qs_det, pairs_qs_int, pairs_det_int = [], [], []
    per_rule = {rid: Counter() for rid in rule_ids}
    parse_fail = 0
    used = 0

    for i, row in enumerate(rows):
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
        used += 1
        det = judge_deterministic(rule_ids, probe)
        qs = row.get("retention_detail") or {}
        if not qs:
            continue
        other, ok = ask_judge(llm, rules, probe)
        if not ok:
            parse_fail += 1
            continue
        for rid in rule_ids:
            pairs_qs_det.append((bool(qs.get(rid)), bool(det.get(rid))))
            pairs_qs_int.append((bool(qs.get(rid)), bool(other.get(rid))))
            pairs_det_int.append((bool(det.get(rid)), bool(other.get(rid))))
            per_rule[rid]["qwen"] += bool(qs.get(rid))
            per_rule[rid]["det"] += bool(det.get(rid))
            per_rule[rid]["internlm"] += bool(other.get(rid))
            per_rule[rid]["n"] += 1
        if (i + 1) % 20 == 0:
            print("  %d/%d episodes" % (i + 1, len(rows)), flush=True)

    a1, k1 = agreement(pairs_qs_det)
    a2, k2 = agreement(pairs_qs_int)
    a3, k3 = agreement(pairs_det_int)

    lines = []
    lines.append("# E8 换族裁判\n")
    lines.append("裁判模型：%s（与 Qwen 不同族）\n" % args.model)
    lines.append("可用 episode：%d，JSON 解析失败：%d\n" % (used, parse_fail))
    lines.append("\n## 两两一致性（逐规则判定，单位为条）\n")
    lines.append("| 对比 | 条数 | 一致率 | Cohen's κ |")
    lines.append("|---|---|---|---|")
    lines.append("| Qwen 自评 vs 机械 | %d | %.3f | %.3f |" % (len(pairs_qs_det), a1, k1))
    lines.append("| Qwen 自评 vs InternLM | %d | %.3f | %.3f |" % (len(pairs_qs_int), a2, k2))
    lines.append("| 机械 vs InternLM | %d | %.3f | %.3f |" % (len(pairs_det_int), a3, k3))
    lines.append("\n## 各规则被判「保留」的比例\n")
    lines.append("| 规则 | n | Qwen 自评 | 机械 | InternLM |")
    lines.append("|---|---|---|---|---|")
    for rid in rule_ids:
        c = per_rule[rid]
        n = c["n"] or 1
        lines.append("| %s | %d | %.3f | %.3f | %.3f |"
                     % (rid, c["n"], c["qwen"] / n, c["det"] / n, c["internlm"] / n))

    text = "\n".join(lines) + "\n"
    print(text)
    outdir = os.path.join(os.path.dirname(_HERE), args.out)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "e8_%s.md" % args.tag), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(outdir, "e8_%s.json" % args.tag), "w", encoding="utf-8") as f:
        json.dump({"used": used, "parse_fail": parse_fail,
                   "pairs": {"qs_det": pairs_qs_det, "qs_int": pairs_qs_int,
                             "det_int": pairs_det_int},
                   "per_rule": {k: dict(v) for k, v in per_rule.items()}},
                  f, ensure_ascii=False)
    print("wrote %s/e8_%s.{md,json}" % (outdir, args.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
