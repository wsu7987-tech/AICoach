# AICoach 意图路由识别模块实施方案树

版本：vNext（基于当前 v1.2.5 代码重新规划）  
目标：先完成一个真正可用的“输入文本 → 模型调用 → Route/Intent 识别 → 前端展示结果”模块。  
当前范围：只做 **意图识别主链路 + 前端界面 + 模型配置重构**。  
暂不纳入：批量评测、Replay、Diff、完整 Trace 后台、部署、主系统接入、多任务编排等。

---

# 0. 执行总规则

## 0.1 通过规则

本方案采用人工 Gate：

- 每个主步骤完成后必须停止。
- 执行方只可以提交“待验收”。
- **只有用户明确回复“通过”后，才允许进入下一主步骤。**
- Codex、自测结果、自动化测试结果都不能代替用户验收。
- “代码写完”“页面能打开”“测试通过”都不等于用户通过。

状态只能是：

- `未开始`
- `执行中`
- `待用户验收`
- `用户通过`
- `用户拒绝 / 需返工`

禁止使用“默认通过”“视为通过”“自动进入下一阶段”。

---

## 0.2 测试规则

本轮禁止持续全局测试。

原则：

- 只规划当前步骤真正必要的验证。
- 每个需要执行测试的节点，必须先告诉用户“准备执行什么测试、为什么需要”。
- **用户同意后才能执行测试。**
- 默认不跑全量 pytest / 全量 frontend test / 全量 E2E。
- 不允许因为“保险起见”扩展测试范围。
- 不允许为了测试方便拆成大量小 Task。

---

## 0.3 设计来源规则

每个关键设计点必须满足至少一项：

1. 有明确 GitHub 项目/文件参考；
2. 用户已明确审批；
3. 若确实找不到参考，必须先标记为“待用户审批的自设计”，审批前不能进入实施。

本方案当前采用的主要参考：

### 前端调试/识别交互

**Dify**
- 仓库：`langgenius/dify`
- 参考：
  - `web/app/components/app/configuration/debug/index.tsx`
- 参考点：
  - Debug / Preview 作为独立执行界面
  - 输入、运行中、结果、错误状态分离
  - 防止重复提交

**Langflow**
- 仓库：`langflow-ai/langflow`
- 参考：
  - `src/frontend/src/components/core/playgroundComponent/chat-view/chat-input/chat-input.tsx`
- 参考点：
  - 输入框运行状态
  - 运行中禁止重复提交
  - 请求失败后恢复输入
  - Playground 作为独立执行入口

**Gradio**
- 仓库：`gradio-app/gradio`
- 参考：
  - `gradio/components/label.py`
  - `demo/image_classification/run.py`
- 参考点：
  - 分类结果按 `label + confidence` 展示
  - Top 分类结果清晰呈现，而不是直接显示原始 JSON

### 模型配置

**Open WebUI**
- 仓库：`open-webui/open-webui`
- 参考：
  - `src/lib/components/AddConnectionModal.svelte`
  - `src/lib/components/admin/Settings/Connections.svelte`
  - `src/lib/apis/openai/index.ts`
  - `backend/open_webui/routers/openai.py`
- 参考点：
  - URL + API Key 的正常连接配置
  - Verify Connection
  - 验证连接后获取模型列表
  - Connection 和 Model 选择分开
  - 用户无需理解 Credential Ref

**Dify**
- 仓库：`langgenius/dify`
- 参考：
  - `web/app/components/header/account-setting/model-provider-page/model-auth/*`
  - `api/libs/key_providers/*`
  - Provider credential 相关实现
- 参考点：
  - Provider / Credential / Model 分层
  - API Key 后端安全保存
  - Model 参数以表单方式配置
  - 凭据不是环境变量名输入框

---

# 1. 实施方案树

```text
AICoach 意图路由识别模块
│
├── Step 1：模型配置模块重构
│   ├── 1.1 重做模型配置页面
│   ├── 1.2 去除 Credential Ref / 调用参数 JSON 等工程字段
│   ├── 1.3 新增真实 API Key 配置
│   ├── 1.4 新增“验证连接”
│   ├── 1.5 验证成功后获取/选择模型
│   └── Gate 1：用户验收
│
├── Step 2：Runtime 意图识别主链路
│   ├── 2.1 实现 POST /api/v1/intent/analyze
│   ├── 2.2 接 Active Model / Runtime Config
│   ├── 2.3 复用 IntentService
│   ├── 2.4 复用 PromptBuilder
│   ├── 2.5 复用 QwenProvider
│   ├── 2.6 返回正式 IntentResult
│   └── Gate 2：用户验收
│
├── Step 3：前端“意图识别”主页面
│   ├── 3.1 重做 App 首页结构
│   ├── 3.2 输入区
│   ├── 3.3 执行状态
│   ├── 3.4 Route 展示
│   ├── 3.5 Intent + confidence 展示
│   ├── 3.6 Slot / Risk / Clarification 展示
│   ├── 3.7 错误状态
│   └── Gate 3：用户验收
│
└── Step 4：真实完整链路验收
    ├── 4.1 使用用户配置的真实模型
    ├── 4.2 前端输入一句话
    ├── 4.3 实际调用模型
    ├── 4.4 返回 Route/Intent
    ├── 4.5 页面展示最终结果
    └── Gate 4：用户最终验收
```

---

# 2. Step 1：模型配置模块重构

状态：`未开始`

## 2.1 目标

把当前偏工程后台的 Model Config：

```text
名称
版本
模型
Base URL
Credential Ref
Structured Output
超时
额外重试
并发
调用参数 JSON
```

重构成正常用户可理解的模型连接配置。

目标界面：

```text
模型配置

API 地址
[ https://... ]

API Key
[ •••••••••••••••• ]

[ 验证连接 ]

连接成功后：

模型
[ qwen-xxx ▼ ]

常用参数
Temperature
Top P

[ 高级设置 ]

[ 保存并使用 ]
```

---

## 2.2 设计来源

参考 Open WebUI：

- `AddConnectionModal.svelte`
  - URL
  - API Key
  - Verify Connection
  - available model IDs

参考 Dify：

- Provider / Credential / Model 分层
- API Key 不以环境变量名形式暴露给用户
- 模型参数使用表单，而不是 JSON textarea

---

## 2.3 当前代码处理原则

### 保留

优先保留后端已有：

- `ModelConfig`
- `ModelConfigSnapshot`
- `ModelProviderFactory`
- `QwenProvider`
- 模型参数校验逻辑中真正有价值的部分

### 改造

- `backend/app/schemas/config.py`
- `backend/app/services/config_service.py`
- `backend/app/api/admin/config.py`
- `frontend/src/ConfigCenter.vue`
- `frontend/src/configApi.ts`

### 从用户界面删除

- `Credential Ref`
- 手工填写 `version`
- `Structured Output`
- `调用参数 JSON`
- `model_config_hash`
- `release_fingerprint`
- 其他纯内部技术字段

是否保留内部版本/Hash机制，由现有代码兼容性决定，但不能再要求用户理解和维护。

---

## 2.4 API Key 设计

用户操作：

```text
API Key
[ *************** ]
```

系统内部：

```text
前端输入
↓
后端接收
↓
安全保存
↓
Provider 使用
```

用户不再操作：

```text
DASHSCOPE_API_KEY
QWEN_API_KEY
credential_ref
环境变量名
```

设计依据：

- Dify provider credential
- Dify key provider / encrypted credential 实现

---

## 2.5 “验证连接”

新增用户动作：

```text
[ 验证连接 ]
```

作用：

```text
API 地址 + API Key
↓
后端发起验证
↓
成功：
  显示“连接成功”
  返回可用模型列表

失败：
  显示明确错误
```

设计依据：

- Open WebUI `verifyOpenAIConnection`
- Open WebUI `/verify`

---

## 2.6 用户在 Gate 1 能看到什么

你应该可以打开页面直接看到：

### 页面变化

1. 原来的 `Credential Ref` 消失。
2. 原来的“调用参数 JSON”消失。
3. 原来的手工“版本”输入从主要配置流程消失。
4. 页面只保留正常人可理解的模型配置字段。
5. 有明确的“验证连接”按钮。
6. 验证成功后可以选择模型。
7. API Key 显示为密码输入状态。

### 你可以人工验证

你可以自己检查：

```text
A. 页面是否清晰
B. 是否还有莫名其妙的工程字段
C. 是否可以直接填 API Key
D. 是否可以直接填 Base URL
E. 是否可以点验证连接
F. 连接失败时提示是否看得懂
G. 连接成功后模型是否可选
H. 是否需要手工填写版本号
I. 是否仍存在 JSON 参数编辑
```

---

## 2.7 Gate 1 通过条件

只有当你明确说：

> Step 1 通过

才进入 Step 2。

如果你认为：

- 页面还难用；
- 字段不合理；
- 交互复杂；
- 仍暴露底层概念；
- Model Config 逻辑不符合预期；

则 Step 1 继续返工。

### 本步骤默认不执行的测试

不默认跑：

- 全量后端 pytest
- 全量 frontend test
- 全量 E2E
- 数据库完整回归

若实现后确实需要执行“验证连接”相关最小测试，必须先向你说明并获得同意。

---

# 3. Step 2：Runtime 意图识别主链路

状态：`等待 Gate 1`

## 3.1 目标

真正实现当前缺失的：

```text
POST /api/v1/intent/analyze
```

形成：

```text
HTTP Request
↓
Runtime Config
↓
IntentService
↓
PromptBuilder
↓
QwenProvider
↓
LLM
↓
Schema / Business Validate
↓
IntentResult
```

---

## 3.2 设计原则

这一阶段不重新设计已有核心 Service。

优先复用：

- `IntentService.analyze()`
- `PromptBuilder`
- `QwenProvider`
- `IntentResult`
- `RuntimeConfiguration`
- `ModelProviderFactory`

当前已有核心逻辑已经完成：

```text
load config
→ verify model
→ build prompt
→ invoke provider
→ parse JSON
→ schema validate
→ business validate
→ IntentResult
```

当前真正缺的是：

> 把它接成正式 Runtime HTTP API。

---

## 3.3 API 输入

沿用当前已有 Contract：

```json
{
  "text": "我想制定一个减脂训练计划",
  "context": {}
}
```

可选：

```text
request_id
conversation_id
```

一期前端不强迫用户填写。

---

## 3.4 API 输出

沿用已有 `IntentResult`：

```json
{
  "request_id": "...",
  "text": "...",
  "route": "training_business",
  "intents": [
    {
      "name": "...",
      "zh": "...",
      "confidence": 0.94
    }
  ],
  "slots": [],
  "risk": null,
  "need_clarification": false,
  "clarification": null
}
```

禁止为了 UI 再发明另一套返回结构。

---

## 3.5 用户在 Gate 2 能看到什么

这一步主要是后端链路，因此你能验证的是：

### 最直接的验证

在 API 文档或简单调用中：

```text
POST /api/v1/intent/analyze
```

已经真实存在。

输入一句话后：

- 不再返回 skeleton。
- 不再是 404。
- 能返回 `IntentResult`。
- Route 是正式七个 Route 之一。
- Intent 有 name / zh / confidence。
- 错误时返回明确错误，而不是未处理异常。

### 你能确认的核心事实

```text
输入文本
↓
真的调用了 IntentService
↓
真的走 Provider
↓
真的返回结构化 IntentResult
```

---

## 3.6 Gate 2 通过条件

只有你明确说：

> Step 2 通过

才能进入 Step 3。

### 本步骤可能需要的最小测试

候选必要验证：

1. 一次 Runtime 成功路径；
2. 一次模型未配置/不可用错误路径。

是否执行测试，必须先向你申请。

不默认执行：

- 全量后端测试
- MySQL 全套测试
- 历史 Task 回归
- 全量 Provider Contract 测试

---

# 4. Step 3：前端“意图识别”主页面

状态：`等待 Gate 2`

## 4.1 目标

把当前：

```text
App
└── ConfigCenter
```

改成当前阶段真正需要的：

```text
AI Coach
├── 意图识别
└── 模型配置
```

默认进入：

```text
意图识别
```

---

## 4.2 输入区

参考：

- Dify Debug
- Langflow Playground

页面必须有明确主输入区：

```text
请输入需要识别的内容

┌──────────────────────────────┐
│ 我想制定一个减脂训练计划       │
│                              │
└──────────────────────────────┘

[ 开始识别 ]
```

---

## 4.3 执行中状态

点击后：

```text
[ 正在识别... ]
```

要求：

- 禁止重复点击；
- 输入文本不能莫名其妙消失；
- 失败后仍能看到原输入；
- 用户明确知道当前系统正在处理。

设计依据：

- Langflow `isBuilding`
- Dify `isResponding`

---

## 4.4 Route 展示

例如：

```text
一级路由

训练业务
training_business
```

注意：

当前 `IntentResult.route` 没有 confidence。

所以：

- 不人为添加 Route confidence；
- 不伪造模型没有返回的数据。

---

## 4.5 Intent 展示

参考 Gradio Label：

```text
意图

制定训练计划     94%
减脂训练         81%
```

使用：

```text
IntentCandidate.zh
IntentCandidate.name
IntentCandidate.confidence
```

按后端当前 Contract 已规定的 confidence 降序展示。

---

## 4.6 Slot 展示

存在 Slot 时：

```text
识别参数

目标      减脂
周期      12周
部位      下肢
```

没有 Slot 时：

- 不显示空的大区域；
- 或显示简洁“未识别到参数”。

不显示原始 JSON。

---

## 4.7 Risk 展示

有 Risk：

```text
风险提示

类型：xxx
等级：中
```

无 Risk：

```text
风险：无
```

---

## 4.8 Clarification 展示

若：

```text
need_clarification = true
```

显示：

```text
需要补充信息

请告诉我……
```

否则不占用主要页面空间。

---

## 4.9 错误状态

用户看到的是可操作错误：

### 未配置模型

```text
当前没有可用模型

[ 前往模型配置 ]
```

### 模型连接失败

```text
无法连接模型服务

[ 重新识别 ]
[ 检查模型配置 ]
```

### 模型输出错误

```text
模型返回结果无法解析

[ 重新识别 ]
```

主页面禁止直接展示：

```text
CONFIG_NOT_READY
MODEL_OUTPUT_SCHEMA_ERROR
release_fingerprint
model_config_hash
credential_ref
```

除非后续专门做开发诊断页。

---

## 4.10 用户在 Gate 3 能看到什么

你打开系统后应该直接看到：

1. 默认首页是“意图识别”，不是配置中心。
2. 有一个明显的文本输入框。
3. 有“开始识别”按钮。
4. 执行时有明确 loading 状态。
5. 成功后有 Route。
6. 有 Intent + confidence。
7. 有 Slot。
8. 有 Risk。
9. 有 Clarification。
10. 错误提示是用户语言。
11. 模型配置是独立入口。
12. 页面不再以 JSON textarea 为核心。

你可以完全通过人工操作判断这一步是否符合预期。

---

## 4.11 Gate 3 通过条件

只有你明确说：

> Step 3 通过

才进入 Step 4。

如果页面：

- 布局不合理；
- 信息优先级不合理；
- 显示工程字段；
- 结果不好理解；
- 输入交互不舒服；

均视为不通过，继续返工。

### 本步骤默认不执行全局测试

候选最小验证：

- 一次前端请求 API 并渲染结果；
- 一次错误状态显示。

执行前必须获得你同意。

---

# 5. Step 4：真实完整链路验收

状态：`等待 Gate 3`

## 5.1 目标

不是 Mock，不是只看单元测试。

真正验证：

```text
前端输入
↓
Runtime API
↓
当前模型配置
↓
真实 OpenAI-compatible Endpoint（Qwen、DeepSeek 或其他兼容服务）
↓
IntentService
↓
IntentResult
↓
前端展示
```

---

## 5.2 验收过程

你能直接操作：

### 1. 配置模型

```text
填写 Base URL
填写 API Key
验证连接
选择模型
保存并使用
```

### 2. 打开“意图识别”

输入：

```text
我想制定一个减脂训练计划
```

点击：

```text
开始识别
```

### 3. 页面显示

至少能看到：

```text
Route
Intent
confidence
Slot（若有）
Risk（若有）
Clarification（若有）
```

---

## 5.3 用户能验证到什么

最终你能确认的不是“某个 Task 写完了”，而是：

> 我真的可以打开这个项目，配置模型，输入一句话，系统真的调用模型，并返回我能看懂的意图路由识别结果。

这才是本阶段完成标准。

---

## 5.4 Gate 4 最终通过

只有用户明确说：

> Step 4 通过 / 本阶段通过

本轮“意图路由识别模块”才算完成。

否则继续修复当前模块。

不允许因为：

- pytest pass
- E2E pass
- Codex 说完成
- 页面截图正常

就自动宣布项目完成。

---

# 6. 暂不进入的后续能力

在 Gate 4 之前，不规划/不实现：

```text
批量测评
Replay
Diff
复杂 Trace UI
调用观测后台
服务状态大盘
部署
主系统接入
多 Provider 市场
Load Balancing
多 Credential
任务 Worker
复杂权限
```

这些能力后续单独规划。

---

# 7. Codex 使用边界

原则：

> 能由当前方案设计、代码审查、GitHub 调研完成的，不丢给 Codex。

Codex 主要负责：

- 实际修改仓库代码；
- 本地运行项目；
- 用户批准后执行必要测试；
- 输出代码修改结果。

不让 Codex负责：

- 产品方案拍脑袋；
- UI 自行设计；
- 自己扩展任务范围；
- 自己新增测试范围；
- 自己决定下一阶段开始。

Codex 每个主步骤完成后必须停止，等待用户 Gate。

---

# 8. 当前执行顺序

```text
当前
↓
Step 1 模型配置重构
↓
用户验收
↓
用户说“通过”
↓
Step 2 Runtime 主链路
↓
用户验收
↓
用户说“通过”
↓
Step 3 前端意图识别页面
↓
用户验收
↓
用户说“通过”
↓
Step 4 真实完整链路
↓
用户最终验收
```

当前只允许进入：

# Step 1：模型配置模块重构
