# agentlab — 长期运行 Agent 状态安全实验底座

对应《长记忆与Skill污染_硬件与实验规划》第 5 节（实验系统结构）与第 14 节阶段 0（可重放实验底座）。

目标不是做一个"记住规则"的问答测试，而是让每一次状态变化都留下可重放的证据，
并且把"模型记住了"与"规则仍然约束真实工具动作"分开测量。

## 1. 设计要点

三条贯穿全项目的原则：

1. **状态对象带来源与权威。** 规则、记忆、Skill、工具输出都是状态对象，各自带
   `source / authority / scope / lifetime / parents / version / evidence`。
   只有 `system_rule` 与 `user_instruction` 可以驱动有后果的工具动作。
2. **Broker 是唯一的效果通道。** 模型只能通过 ToolBroker 影响资源，策略检查与效果记录
   发生在同一点，因此"模型声称做了"和"资源真的变了"不会混为一谈。
3. **重放不调用模型。** 事件日志 + 内容寻址证据目录，使同一 session 可以被重新读取、
   逐事件比对，而不需要重新推理。

## 2. 模块

| 模块 | 作用 | 对应文档 |
|---|---|---|
| `schema.py` | 事件/状态对象 schema，§5 全字段 | §5 |
| `store.py` | 追加式事件日志、blob、`replay()`、`diff()` | §5 |
| `policy.py` | 六类规则与检查（资源/工具/网络/审批/期限/Skill） | §6.1 |
| `tools.py` | 文件、SQLite、本地网络三类工具，记录资源端效果 | §5 |
| `broker.py` | 策略闸门 + 执行 + 证据记录，`enforced`/`open` 两种模式 | §2.2 |
| `context.py` | 上下文管理与四种压缩策略 | §6.1 |
| `memory.py` | 长期记忆：来源、权威、依赖图、撤销级联 | §6.3 / §6.4 |
| `skills.py` | Skill 冻结包、内容哈希、审查绑定 | §6.2 |
| `pollute.py` | 四入口污染注入与危害分类 | §6.3 |
| `tasks.py` | 两个合法任务域、13 个任务 | §6.1 |
| `agent.py` | Episode 循环 | §5 |
| `metrics.py` | 规则保持（语义判分）、违规率、完成率 | §8 |
| `experiments/` | E1 规则保持、E2 污染传播、预算标定 | §6 |

## 3. 压缩策略与 H1 的对应

四种策略唯一的差别是"上下文被重写时，规则块发生了什么"：

| 策略 | 对规则块的处理 |
|---|---|
| `none` | 不压缩，历史全部保留（对照组） |
| `truncate` | 丢弃最早的观测，system 与任务保留 → 规则天然存活 |
| `uniform_summary` | 把含规则的全部历史压成一段普通摘要 → 规则可能被丢掉 |
| `typed_summary` | 按 事实/流程/偏好/约束/权限 分节压缩 |
| `typed_summary_protected` | 类型化摘要 + 每轮重新注入逐字规则通道 |

同时记录两套指标，避免把"提示里有"当成"模型会遵守"：

- `harness_retention`：压缩后提示里是否仍出现该规则原文（确定性检查）；
- `retention`：让模型复述当前约束，再用判分器逐条判断语义是否保留。

## 4. 运行

服务器（AutoDL 4090，模型 `Qwen2.5-7B-Instruct`，vLLM 0.32 已就绪）：

```bash
cd /root/autodl-tmp/work/lab

# 本地单元测试（无需 GPU）
python agentlab/tests/test_core.py

# 触发压缩的预算标定
python experiments/calibrate_budget.py A4 500,700,900,1200

# E1：任务 × 策略 × 压缩压力
python experiments/e1_rule_retention.py \
  --tasks A1,A4,B1,B5 \
  --strategies none,truncate,uniform_summary,typed_summary,typed_summary_protected \
  --budgets 1200,800,550 --tag e1_full

# E2：五入口污染 × 两种载荷 × 有无防御
python experiments/e2_pollution.py --task B1 \
  --layers none,creation,activation,storage,retrieval,skill \
  --payloads hidden_instruction,scope_widening --modes open,enforced
```

结果写入 `results/`：每次运行一行 JSONL，另附 markdown 汇总表；事件日志在
`results/store_<tag>/events.jsonl`。

## 5. 当前边界（写进论文前必须补的）

1. **上下文规模偏小。** 现阶段提示 400–1000 token，压缩是"小尺度"触发。
   文档阶段 1 要求的 8K/32K 需要在更大任务与更长轨迹上重跑，结论不能直接外推。
2. **判分器与生成器同模型。** 规则保持由同一个 7B 模型判分，存在自评偏差；
   需要加入独立判分器或规则化校验作为对照。
3. **单一模型、单一工具版本。** 跨模型、跨工具版本迁移（H6）尚未接入。
4. **污染强度未做梯度。** 目前是"单条注入"，尚未做 5%/20% 状态污染密度。
5. **E1 的"无压缩"在预算溢出时不截断**，这是有意的对照组设计，但需要在论文中说明，
   否则会被理解为基线不公平。

## 6. 工程约定

- 服务器上 `pip`/`uv` 走阿里云镜像且**必须绕开代理**，否则索引页被截断；
- 下模型走 ModelScope **直连**（9.6 MB/s），不要开代理（0.5 MB/s）；
- vLLM 0.32 已移除 `--disable-log-requests`，且需要 `ninja` 在 PATH 中；
- 无认证信息的命令一律写进脚本文件执行，避免 shell 展开吃掉 `$PATH` 之类变量。
