# 03 Intent 路由与动态 Prompt 设计

## 1. Runtime Intent Contract

```json
{
  "text": "我要做深蹲",
  "route": "training_business",
  "intents": [
    {"name": "start_training", "zh": "想开始训练", "confidence": 0.98}
  ],
  "slots": [
    {"name": "exercise", "zh": "动作", "value": "深蹲", "start": 3, "end": 5, "confidence": 0.99}
  ],
  "risk": null,
  "need_clarification": false,
  "clarification": null
}
```

`start/end` 统一使用 **UTF-16 code-unit offset**，区间语义为 `[start,end)`（start inclusive，end exclusive），与 Java/JavaScript 字符串索引口径一致。服务端必须校验 span，不完全相信 LLM 自行计数：
1. 将 `text` 转为 UTF-16 code-unit 后，若 `text[start:end]` 等于 slot `value`（枚举槽位还可等于该枚举值的 display/aliases）→ 通过；
2. 不通过但 `value`（或其别名）在 `text` 中恰好出现一次 → 服务端按该位置重算 start/end；
3. 否则（未找到或多处歧义）→ 丢弃该 slot，Trace `validation_json` 记录 `SLOT_SPAN_INVALID`（含原 slot），**不使请求失败**。

`risk` 必须存在，可为 null 或：

```json
{"type": "pain_injury", "zh": "疼痛/伤病", "level": "high"}
```

## 2. Runtime 与 Debug Output 分离

模型结构化输出可包含：

- Runtime 业务字段
- `reason_summary`
- `evidence`

Parser 最终只把业务字段构造成 `IntentResult`；调试字段仅写 Trace/Admin。

禁止把 Final Prompt、Raw Request、Raw Response、Model Params、Provider extras 放入 Runtime Response。

## 3. 一级 Route Contract

一期 Runtime 一级 Route key 固定为：

- `training_business`
- `information_query`
- `sports_knowledge`
- `safety`
- `dialogue_device_control`
- `social_chat`
- `unknown`

这些 key 是 Java/下游依赖的稳定 API Contract，配置中心不得修改、删除、新增，**也不得 disable**。Draft Validate / Publish 必须校验：routes 恰好包含这 7 个 key 且全部 enabled，否则拒绝发布。可配置的是中文名、描述、Few-shot、二级 Intent、Slot、Enum/Alias 以及既有 Route 下的映射。

所有 Route 采用相同的澄清约束：`need_clarification=false -> clarification=null`；`need_clarification=true -> clarification` 必须为非空字符串。

**`intents` 基数规则：** Runtime Contract 与 `LLMStructuredIntentOutput` 的 `intents` 为 `0..n`，**不设 `min_length`**，所有路由一致。空 `intents` 不会使请求失败；Trace `validation_json` 统一记录 `INTENTS_EMPTY`。计划中的结果匹配验证对训练业务只比较一级 Route，其他业务还需比较二级 Intent。输出 Schema 不得使用 `minItems`（部分 Qwen strict 模式不支持）。完整样例见 `docs/10`。

## 4. 动态 Prompt

最终 Prompt 由：

```text
Stable System/Task Template
+ Routes
+ Intents
+ Slots
+ Enums/Aliases
+ Few-shot Examples
+ Runtime JSON Schema instruction
+ User text/context
```

业务枚举来自 Config Release Snapshot，不在 Python Router 代码中维护第二份。

## 5. Structured Output 策略

首选：Provider 原生 JSON Schema strict 模式。

```text
Pydantic LLMStructuredIntentOutput
-> JSON Schema
-> Provider response_format=json_schema
-> JSON parse
-> Pydantic validate
-> business validate
```

若实际模型不支持 JSON Schema，可在 Model Config 明确使用 `json_object`：

- Prompt 中必须明确 JSON 输出要求；
- 仍必须 Pydantic 校验；
- 不允许 silent fallback；
- Trace 必须记录实际 response mode。

## 6. Model Config 语义

Managed Model 独立于业务配置发布，至少包含：

- provider
- model
- base_url 配置引用/非 secret 地址
- credential_id（关联应用层加密保存的 Provider Credential）
- temperature
- max_tokens
- timeout_seconds
- max_retries（首次调用之外允许的最大重试次数；总 Attempt ≤ 1 + max_retries；仅由 Provider 执行）
- max_concurrency
- structured_output_mode
- enabled

模型身份字段不原地修改；Trace/Evaluation 保存每次实际使用的 ManagedModel 非 Secret 快照。
旧 `ModelConfig` Contract 与 ENV Credential 兼容路径已移除。

Disable 语义：
- 默认 ManagedModel 禁止直接 disable，必须先设置其他默认模型；
- 正在运行的 Evaluation 使用创建 Run 时冻结的 ManagedModel snapshot；之后 disable 不影响该 Run；
- disabled ManagedModel 不允许用于新 Runtime、Debug 或 Evaluation 调用；
- 历史 Trace/Replay 读取其非 Secret snapshot；一期不物理删除 ManagedModel。

Runtime：业务规则使用 Active Release；模型使用请求的 `model_uid`，未指定时使用 Runtime 默认模型。

Admin Debug/Evaluation：可选 `model_uid` override；未指定时使用 Runtime 默认模型。

Trace 必须记录最终 `managed_model_uid` + 非 Secret snapshot。

当 `structured_output_mode` 为 `json_schema` / `json_object` 时，`max_tokens` 必须为空并且 Provider 不发送该参数；这是 Qwen Structured Output 的兼容性约束。

## 7. Release / Config Snapshot

Business Config Snapshot 只包含业务配置：

```json
{
  "schema_version": 1,
  "routes": [],
  "intents": [],
  "slots": [],
  "enums": {},
  "examples": [],
  "prompt_template": {
    "system": "...",
    "rules": [],
    "include_examples": true
  }
}
```

`include_examples=false` 时保留 Examples 数据，但 PromptBuilder 不向 Route 或 Intent 模块
注入典型说法；重新开启后继续使用已启用的样例。

Release 不包含任何模型字段；模型选择不进入 Business Snapshot，也不参与业务配置发布。

### Bootstrap / Draft 顶层 Schema

`bootstrap/initial-config.v1.json` 必须与 Business Config Draft/Snapshot 使用同一顶层 Schema，且仅允许：

```text
schema_version / routes / intents / slots / enums / examples / prompt_template
```

固定 7 Route Contract 属于代码/API Contract，不作为 Bootstrap 额外顶层字段重复存储；调研状态、审批状态等元数据也不得进入 Draft/Snapshot/hash。导入时应 `extra=forbid` 或等价严格校验，禁止静默丢弃未知顶层字段。


`config_snapshot_hash = SHA256(canonical business snapshot)` 仅用于服务端完整性校验。
历史 Business Snapshot 不可变。Trace 记录 `release_id / config_snapshot_hash / managed_model_uid / managed_model_snapshot`。

## 8. 训练业务规则

训练 Intent 与其他 Intent 使用相同的识别、参数提取、默认值和缺参澄清逻辑。计划中的结果匹配验证对训练业务只比较一级 Route；该验证功能尚未实现。

## 9. Safety 一期规则

一期没有关键词 Safety Guard。文本仍走 LLM；模型可输出 `route=safety` 和 `risk`。

未来 Safety PreRouter 必须作为独立前置组件接入，不改变本期 Runtime Contract。

## 10. Intent 快速调整机制

后期业务 Intent 调整默认不改代码，使用配置发布：

```text
修改 Draft 中 Intent/Slot/Enum/Alias/Few-shot/Prompt
-> Validate
-> Preview Final Prompt
-> 跑回归 Evaluation
-> Publish 新 immutable Release
-> Active Release 原子切换
```

因此新增二级 Intent、补同义词、修改描述、增加 Slot/枚举、优化 Few-shot/Prompt，都可以快速上线并可随时追溯/回退。

但一级 Route key 属于对外 Contract。新增、删除、重命名一级 Route 或修改 `IntentResult` Schema 时，必须作为 API Contract 变更处理，而不是普通配置修改。

## 11. 二级 Intent 初始归属表（Bootstrap）

`bootstrap/initial-config.v1.json` 内置下表，覆盖评估集 Excel 模板“期望二级意图”下拉的全部 39 个值，外加通用的 `start_training`。
**状态：草案，待产品确认**（尤其是 `疲劳咨询` 的归属）。确认后只需修改 Bootstrap/Draft 配置，不改代码；归属变化需重新跑回归 Evaluation 再发布。

| # | 二级 Intent（name） | 中文名（Excel 下拉值） | 一级 Route | 备注 |
|---|---|---|---|---|
| 1 | `start_training` | 开始训练（别名：想开始训练） | `training_business`（训练业务） |  |
| 2 | `generate_single_course` | 生成单次课程 | `training_business`（训练业务） |  |
| 3 | `follow_plan` | 按计划训练 | `training_business`（训练业务） |  |
| 4 | `create_long_term_plan` | 制定长期计划 | `training_business`（训练业务） |  |
| 5 | `adjust_schedule` | 调整计划/日程 | `training_business`（训练业务） |  |
| 6 | `change_body_part` | 更换训练部位 | `training_business`（训练业务） |  |
| 7 | `query_schedule` | 查日程 | `information_query`（信息查询） |  |
| 8 | `query_progress` | 查进度 | `information_query`（信息查询） |  |
| 9 | `query_body_status` | 查身体状态（别名：查询身体状态） | `information_query`（信息查询） |  |
| 10 | `query_assessment` | 查测评报告 | `information_query`（信息查询） |  |
| 11 | `exercise_knowledge` | 动作/训练知识（别名：动作训练知识） | `sports_knowledge`（运动知识咨询） |  |
| 12 | `health_knowledge` | 运动健康知识 | `sports_knowledge`（运动知识咨询） |  |
| 13 | `device_usage_knowledge` | 设备使用知识 | `sports_knowledge`（运动知识咨询） |  |
| 14 | `fatigue_consultation` | 疲劳咨询 | `sports_knowledge`（运动知识咨询） | 待产品确认：归 sports_knowledge 还是 safety（历史讨论中“腿有点酸还能练吗”曾期望 safety/fatigue） |
| 15 | `injury_pain` | 伤病/疼痛（别名：伤病或疼痛） | `safety`（身体风险/安全） |  |
| 16 | `emergency_stop` | 紧急停止 | `safety`（身体风险/安全） |  |
| 17 | `training_safety_anomaly` | 训练中安全异常 | `safety`（身体风险/安全） |  |
| 18 | `confirm` | 确认 | `dialogue_device_control`（对话与设备控制） |  |
| 19 | `cancel` | 取消 | `dialogue_device_control`（对话与设备控制） |  |
| 20 | `modify` | 修改 | `dialogue_device_control`（对话与设备控制） |  |
| 21 | `pause` | 暂停 | `dialogue_device_control`（对话与设备控制） |  |
| 22 | `resume` | 继续 | `dialogue_device_control`（对话与设备控制） |  |
| 23 | `volume_up` | 音量增大 | `dialogue_device_control`（对话与设备控制） |  |
| 24 | `volume_down` | 音量减小 | `dialogue_device_control`（对话与设备控制） |  |
| 25 | `mute` | 静音 | `dialogue_device_control`（对话与设备控制） |  |
| 26 | `unmute` | 取消静音 | `dialogue_device_control`（对话与设备控制） |  |
| 27 | `brightness_up` | 亮度增加 | `dialogue_device_control`（对话与设备控制） |  |
| 28 | `brightness_down` | 亮度降低 | `dialogue_device_control`（对话与设备控制） |  |
| 29 | `screen_toggle` | 息屏/亮屏 | `dialogue_device_control`（对话与设备控制） |  |
| 30 | `device_connect` | 设备连接 | `dialogue_device_control`（对话与设备控制） |  |
| 31 | `device_status_query` | 设备状态查询 | `dialogue_device_control`（对话与设备控制） |  |
| 32 | `adjust_training_weight` | 训练重量调整 | `dialogue_device_control`（对话与设备控制） |  |
| 33 | `switch_training_mode` | 训练模式切换 | `dialogue_device_control`（对话与设备控制） |  |
| 34 | `ambient_light` | 灯光/氛围 | `dialogue_device_control`（对话与设备控制） |  |
| 35 | `greeting` | 问候 | `social_chat`（社交/闲聊） |  |
| 36 | `general_social_chat` | 普通闲聊（别名：一般闲聊） | `social_chat`（社交/闲聊） |  |
| 37 | `emotional_support` | 情感陪伴/鼓励 | `social_chat`（社交/闲聊） |  |
| 38 | `unknown` | 无法识别（别名：未知） | `unknown`（未知/不支持） |  |
| 39 | `out_of_capability` | 超出能力 | `unknown`（未知/不支持） |  |
| 40 | `unsupported_feature` | 暂不支持功能 | `unknown`（未知/不支持） |  |

- 计划中的结果匹配验证对训练业务只比较一级 Route；训练类二级 Intent 仍按相同规则识别和返回。
- 上线前研发需让产品在配置中心或 Excel“意图归属参考”页确认归属表。
