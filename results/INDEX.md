# 结果索引

由 `experiments/make_index.py` 生成，勿手工编辑。
每个实验的 `.jsonl`（逐 episode 原始记录）与同名 `.md`（汇总表）。

**排除项**（早期版本或 tag 复用造成事件库混入多遍，不用于结论）：

- `e1_e1_full.jsonl` — prompt token 计数错误时期的产物
- `e2_e2_v1.jsonl` — 早期版本
- `e3_e3_pilot.jsonl` — 早期版本
- `e4_e4_full.jsonl` — tag 复用，事件库混入多遍
- `e6_e6_v1.jsonl` — 整批 120 个 episode 全部异常退出

## e1

| 文件 | episodes | 备注 |
|---|---|---|
| e1_e1_full.jsonl | 60 | ⚠ 已排除 |
| e1_e1_v2.jsonl | 60 | |
| e1_e1_v3.jsonl | 60 | |
| e1_e1var_r1.jsonl | 24 | |
| e1_e1var_r2.jsonl | 24 | |
| e1_e1var_r3.jsonl | 24 | |
| e1_smoke.jsonl | 2 | |

## e1b

| 文件 | episodes | 备注 |
|---|---|---|
| e1b_e1b_full.jsonl | 144 | |
| e1b_e1b_pilot.jsonl | 16 | |

## e1long

| 文件 | episodes | 备注 |
|---|---|---|
| e1long_e1long_v2.jsonl | 36 | |

## e2

| 文件 | episodes | 备注 |
|---|---|---|
| e2_e2_aligned_hidden_instruction.jsonl | 12 | |
| e2_e2_aligned_scope_widening.jsonl | 12 | |
| e2_e2_v1.jsonl | 22 | ⚠ 已排除 |
| e2_e2_weak_hidden_instruction.jsonl | 12 | |
| e2_e2_weak_scope_widening.jsonl | 12 | |
| e2_e2v2_aligned.jsonl | 60 | |
| e2_e2v2_weak.jsonl | 60 | |

## e3

| 文件 | episodes | 备注 |
|---|---|---|
| e3_e3_B1_enforced.jsonl | 100 | |
| e3_e3_B3.jsonl | 100 | |
| e3_e3_B4.jsonl | 100 | |
| e3_e3_B5.jsonl | 100 | |
| e3_e3_full.jsonl | 100 | |
| e3_e3_pilot.jsonl | 15 | ⚠ 已排除 |
| e3_e3g_B1.jsonl | 100 | |
| e3_e3g_B3.jsonl | 100 | |
| e3_e3g_B4.jsonl | 100 | |
| e3_e3g_B5.jsonl | 100 | |

## e3b

| 文件 | episodes | 备注 |
|---|---|---|
| e3b_e3b_full.jsonl | 60 | |

## e4

| 文件 | episodes | 备注 |
|---|---|---|
| e4_e4_full.jsonl | 60 | ⚠ 已排除 |
| e4_e4_v2.jsonl | 60 | |

## e6

| 文件 | episodes | 备注 |
|---|---|---|
| e6_e6_v1.jsonl | 120 | ⚠ 已排除 |
| e6_e6_v2.jsonl | 120 | |
| e6_e6_v3b.jsonl | 240 | |

## e10

| 文件 | episodes | 备注 |
|---|---|---|
| e10_e10_v1.jsonl | 120 | |

## repro

| 文件 | episodes | 备注 |
|---|---|---|
| repro_repro.jsonl | 13 | |

