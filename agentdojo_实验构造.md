# AgentDojo 实验构造（arXiv:2406.13352v3 全文 + 仓库 main 分支源码已核对）

## 一、任务构造
4 个 suite：Workspace 24 工具/40 任务/6 注入；Slack 11/21/5；Travel 28/20/7；Banking 11/16/9。合计 **74 工具、97 用户任务、27 注入任务**（表 1 合计栏写 70，与分项和 74 矛盾，正文用 74）。安全用例=套内笛卡尔积：40×6+21×5+20×7+16×9=**629**。数据结构：UserTask{PROMPT, ground_truth(pre)→[FunctionCall], utility(output, pre, post, strict)}；InjectionTask{GOAL, ground_truth, security(...)}。环境是可变的 pydantic 状态（邮件/日历/云盘/银行/航班），用 GPT-4o/Claude 3 Opus 生成数据后人工审核；敏感处留占位符，攻击只往"该任务必经工具"输出的占位符里填（get_injection_candidates 靠 ground_truth 调用序列筛），保证注入必被读到。

## 二、判据构造
不用字符串匹配，也不用 LLM 评审（注入会连带劫持评审模型）。跑前 `pre = env.model_copy(deep=True)`，跑后做**对象级状态差分**；只读任务另用工具调用轨迹（utility_from_traces）。例：utility 断言 post 日历新增了 title/start 都匹配的事件；security 断言 post 已发件箱出现"收件人=攻击者地址"的条目。三指标：benign utility（97 任务，无攻击）；utility under attack = P(utility ∧ ¬attack)，其补集称 untargeted ASR；**targeted ASR 只由 security 判定，与任务是否完成无关**。

## 三、统计协议
每个 (用户任务, 注入任务, 攻击, 防御) 组合**只跑 1 次**；OpenAI 封装默认 temperature=0.0，无多 seed，不报均值±std。唯一重试是 `for _ in range(3)`（仅输出为 None/Abort 时重跑，属容错）。报 **95% 二项比例 CI**（statsmodels proportion_confint，括号内 ±半宽）：GPT-4o benign 69.0%±3.6；Claude 3 Opus 66.6%±3.7 / 52.5%±3.9 / ASR 11.3%±2.5；跑满 629 例约 35 美元（97 例 4 美元）。攻击合并成"任一成功"的 Max 自适应口径（+10 个点）。防御 4 基线：分隔符、BERT 检测器（benign 41.5%）、prompt sandwiching（benign 85.5%，反升）、tool filter（ASR 7.5%）。攻击 4 基线：ignore previous instructions、InjecAgent 模板、TODO:{goal}、Important message（45.8%）。可比性=固定 system prompt、同一 629 用例、同一温度与 YAML 工具输出格式，只换被测组件。攻击知识消融：猜对用户名 +0.3%、模型名 −1.0%、都对 +1.9%、猜错 −22.6%/−22.1%。

## 四、可继承的具体做法
1. 用例=用户任务×注入任务，但必须同时报 benign utility，否则低 ASR 分不清"防御强"与"模型不会用工具"。
2. utility/security 各写成 `(output, pre, post)→bool` 的确定性函数，深拷贝后对象级 diff；禁 LLM-judge。
3. 钉死 security 语义：源码里 **True=攻击成功**（与函数名相反，极易读错）；报表同时给 targeted ASR 与 utility under attack。
4. 注入只放"必经工具"输出的占位符，用 ground_truth 调用序列自动筛，否则大量用例空转。
5. 单跑 temperature=0 + 按用例算 95% 二项 CI 即可；但 n 要按真实任务数（benign 是 97——表 3 的 ±3.7 反推 n≈629，属口径瑕疵）。
