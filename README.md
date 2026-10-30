# skilling

长记忆与 Skill 污染的实验底座与数据。

一个可重放的事件溯源（event-sourced）代理底座，用来研究：上下文压缩会不会让系统规则丢失，
以及被污染的内容经由不同"载体"（文档 / 记忆 / Skill / 工具输出）进入系统时，
采信率为什么差别巨大。

单卡 RTX 4090 24GB + Qwen2.5-7B-Instruct + vLLM，全部结论来自服务器实跑。

---

## 仓库结构

```
agentlab/            底座（纯标准库，可离线重放）
  schema.py          溯源元组：authority / transformation / verification
  store.py           追加式事件日志、重放、diff、确定性校验
  policy.py          R1–R6 规则与执行（含按主机名限定的网络规则）
  tools.py           文件系统 / SQLite / 本地 HTTP 工具，返回资源真实效应
  broker.py          模型意图到资源效应的唯一通道（enforced / open 两种模式）
  context.py         五种压缩策略与 token 预算控制
  memory.py          带溯源与依赖撤销的长期记忆
  skills.py          冻结技能包、内容哈希、审查后替换的拦截
  pollute.py         六个注入入口与载荷分类
  tasks.py           任务集（A 域重构、B 域文档、B7 技能路径、B8 长上下文、X1 过拒答探针）
  agent.py           episode 主循环、探针、强制压缩
  judge.py           确定性规则判分（与 LLM 判分互为独立失败模式）
  metrics.py         规则保持、违规、效用

experiments/         实验脚本
  e1_rule_retention.py     压缩 → 规则保持（预算驱动）
  e1b_forced_compaction.py 同样的效应，用"每 K 轮强制压缩"做干净自变量
  e1_long_context.py       ~10K token 真实上下文里的压缩悬崖
  e2_pollution.py          注入入口 / 载荷强度
  e3_carrier.py            载体转换（文档 / 记忆 / Skill / 工具输出）
  e3b_skill_path.py        真实 SkillLoader 路径与哈希绑定
  e4_over_refusal.py       过拒答代价（合法请求被规则误伤）
  e5_judge_agreement.py    机械判分 vs 自评判分的一致性
  e6_memory_frames.py      记忆通道机制：标签如何决定采信

results/             实跑数据（jsonl + 每组的 md 汇总）
阶段1结果.md          第一批结论
阶段1结果_第二批.md    第二批结论（含对第一批的修正）
```

---

## 关键结论（截至第二批）

1. **压缩会让规则丢失，剂量-反应很陡。** `uniform_summary` 在 2.4 次压缩后
   保持率约 3%（机械判分）；类型化摘要与受保护通道在任何压缩次数下都是 1.00。
2. **自评判分器系统性偏松。** 846 条判分比对中，单边分歧 18/19 是自评说"保留"
   而机械判分说"没保留"，且集中在低信息量的探针上——也就是压缩造成的那些。
3. **载体决定采信率。** 同一段文字：记忆 / Skill 0.91，文档 0.13，工具输出 0.11。
4. **决定采信的不是"记忆"，而是归属。** 同样注入点、同样文字，
   `[检索结果]` 0.20 vs `[历史对话摘要]` 1.00。
5. **过拒答可以量化也可以消除。** 一条合法请求在现行规则下 20/20 被拦、任务 0% 完成；
   把规则限定到主机名后成功率回到 100%，外部地址仍然 100% 被拦。

---

## 复现

底座无第三方依赖（`judge.py` / `metrics.py` 也不依赖任何模型），可以直接跑测试：

```bash
python agentlab/tests/test_core.py      # 44 项，全绿
```

跑真实实验需要 vLLM 服务与模型权重：

```bash
V=/path/to/vllm/bin
export PATH="$V:$PATH"
export VLLM_USE_FLASHINFER_SAMPLER=0
$V/python -m vllm.entrypoints.openai.api_server \
  --model /path/to/Qwen2.5-7B-Instruct --served-model-name qwen2.5-7b \
  --max-model-len 32768 --gpu-memory-utilization 0.92 \
  --port 8000 --host 127.0.0.1 --dtype bfloat16 --no-enable-log-requests
```

然后例如：

```bash
python experiments/e3_carrier.py --task B1 \
  --carriers none,document,memory,skill,tool_output \
  --modes open --repeats 20 --tag e3_v1
```

**重跑纪律**：每次重跑必须用新的 tag。事件库是累积的，复用 tag 会把不同批次
写进同一个 session id，重放时事件混在一起（已经踩过一次）。

---

## 已知局限

- 所有结论来自**一个模型、一种解码配置**，只能做机制演示，不能外推为普适规律。
- vLLM 在 temperature=0 且指定 seed 时**仍不保证逐位复现**，因此全部结论按分布报，
  给 n 与 Wilson 区间。
- 机械判分器目前**不处理否定语境**：判断的是"话题有没有出现"，不是"禁止有没有保留"。
  绝对值不可信，只读方向与相对比较。
- 记忆注入是上下文拼接，不是带检索分数与来源元数据的真实 RAG。
- 补全"规则丢失 → 违规"这一环的诱惑任务尚在建设中（见最新一批报告）。
