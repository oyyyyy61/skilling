#!/bin/bash
# 排队实验的预检：在无人值守跑之前，验证每个实验的入口假设。
#
# 存在的理由：这些实验是排队的，一个依赖缺失或导入失败要等几小时才暴露。
# 一次预检 30 秒，能省掉整条链的重跑。
#
# 用法：bash experiments/preflight.sh [lab_root]
set -u
export PATH=/root/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH
LAB="${1:-/root/autodl-tmp/work/lab}"
cd "$LAB" || { echo "no such dir: $LAB"; exit 1; }

echo "=== 依赖文件 ==="
for f in results/store_e1b_full results/e1b_e1b_full.jsonl \
         results/store_e7_v2 results/e7_e7_v2.jsonl; do
  if [ -e "$f" ]; then echo "  OK   $f"; else echo "  MISS $f"; fi
done
if [ -d /root/autodl-tmp/models/internlm2_5-7b-chat ]; then
  echo "  OK   internlm dir ($(ls /root/autodl-tmp/models/internlm2_5-7b-chat | wc -l) files)"
else
  echo "  MISS internlm"
fi

echo
echo "=== 脚本可导入 ==="
for s in e10_attribution e11_rule_fork e12_replay_fork e8_cross_family_judge \
         e6_memory_frames e5b_polarity_delta e1long_peek diag_dup qa_results; do
  [ -f "experiments/$s.py" ] || { echo "  MISS experiments/$s.py"; continue; }
  python -c "import importlib.util as u; s=u.spec_from_file_location('m','experiments/$s.py'); m=u.module_from_spec(s); s.loader.exec_module(m)" 2>/dev/null \
    && echo "  OK   $s" || echo "  FAIL $s"
done

echo
echo "=== 端口 ==="
for p in 8000 8001; do
  c=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" http://127.0.0.1:$p/health 2>/dev/null)
  echo "  $p -> $c"
done

echo
echo "=== watcher 存活 ==="
# 注意：用内联 bash -c 启动的 watcher，命令行里不会有脚本名，
# 只能靠它轮询的日志文件名（chain.log 等）认出来。
ps -eo pid,args | awk '/run_e10b|run_e11|run_priority|chain\.log/ && !/awk/ {
  printf "  %s %s\n", $1, substr($0, index($0,$2), 46)}'
echo
echo "（没有输出 = 没有 watcher 在跑，需要手动启动）"
