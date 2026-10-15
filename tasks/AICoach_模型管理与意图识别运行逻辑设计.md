# AICoach 模型管理与意图识别运行逻辑设计

版本：vNext / Step 1 设计确认版  
基线：AICoach v1.2.5  
用途：作为 Codex 后续实现模型管理、模型切换、Credential、安全存储、Runtime 调用及调用结果留痕的设计依据。

---

# 1. 当前阶段目标

本阶段只完成：

1. 模型管理；
2. 模型凭据安全保存；
3. 多模型保存；
4. 默认模型；
5. 意图识别时按请求切换模型；
6. 成功识别结果落库；
7. 失败调用单独记录；
8. 前端模型管理页面；
9. 前端意图识别页面。

当前不扩展：

- 批量评测；
- Replay / Diff；
- 复杂 Trace 后台；
- 多 Credential 轮换中心；
- Load Balancing；
- RBAC；
- Provider 市场；
- 任务编排；
- 主系统集成。

---

# 2. 核心业务定义

## 2.1 “模型”是什么

产品层的“模型”由以下核心信息组成：

```text
模型名称 model_name
+
调用地址 base_url
```

这两个值共同决定一个模型的唯一身份。

例如：

```text
qwen-plus
https://dashscope.aliyuncs.com/compatible-mode/v1
```

与：

```text
qwen-plus
https://other-gateway.example.com/v1
```

视为两个不同模型。

---

# 3. model_uid

系统为每个模型生成稳定唯一标识：

```text
model_uid
```

生成依据：

```text
normalized(base_url) + model_name
```

可使用稳定 hash 生成，例如：

```text
SHA256(normalized_base_url + "\n" + normalized_model_name)
```

最终对外可使用：

```text
mdl_<hash-short-or-full>
```

要求：

- model_uid 由系统生成；
- 用户不能编辑；
- 同一 `base_url + model_name` 不允许重复创建；
- model_uid 一旦创建永久不变；
- API Key 不参与 model_uid；
- display_name 不参与 model_uid；
- temperature / top_p 等参数不参与 model_uid。

---

# 4. API Key 与模型关系

创建模型时，用户一次性填写：

```text
显示名称
Base URL
API Key
模型名称
模型参数
```

产品体验上：

> API Key 是“创建模型”表单中的一个字段。

但后端实现必须分层：

```text
Model
+
Credential
```

真实 API Key 不允许直接进入 Model 表普通字段。

---

# 5. Credential 方案

采用独立 Credential 存储。

参考：

- Dify Provider Credential
- Dify encrypted_config / credential update
- Open WebUI connection verify

## 5.1 新增 provider_credential

最小字段建议：

```text
id
credential_uid
encrypted_secret
secret_hint
created_at
updated_at
```

可选：

```text
last_verified_at
last_verify_status
```

不要扩展：

- 多 Credential Pool；
- Credential Rotation Center；
- RBAC；
- Load Balancing。

---

## 5.2 API Key 安全规则

必须满足：

1. 数据库存密文，不存明文；
2. 主加密密钥来自环境变量 / Kubernetes Secret；
3. 主加密密钥不进入 DB；
4. 所有 Pod 使用相同主密钥；
5. GET 接口永远不返回真实 API Key；
6. 前端刷新时只能拿到：
   - 已配置；
   - 遮罩值，如 `••••ABCD`；
7. API Key 不允许进入：
   - 日志；
   - Trace；
   - raw_request_json；
   - raw_response_json；
   - error_message；
   - API Response；
8. API Key 更新属于 Credential 更新，不是新模型。

---

# 6. Model 数据结构

产品语义已从旧 `ModelConfig Version` 转换为“模型”，由 `ManagedModel` 独立承载：

```text
id
model_uid
display_name
provider（仅后端内部协议适配器标识，不是用户选择的厂商）
model_name
base_url
credential_id
params_json
timeout_seconds
max_retries
max_concurrency
enabled
created_at
updated_at
```

注意：

- `model_name` + `base_url` 决定模型身份；
- 一期统一按 OpenAI-compatible 协议接入，用户不选择 Provider；
- Qwen、DeepSeek 或其他服务由 `base_url + model_name` 表达，`provider` 只用于后端内部选择协议适配器；
- API Key 不进入模型 hash；
- API Key 不进入历史调用快照；
- Credential 必须使用新的加密存储，不再支持旧 ENV 引用路径。

---

# 7. Credential 解析

Runtime Credential 解析顺序：

```text
model.credential_id
↓
查询 Provider Credential
↓
使用部署主密钥解密到短生命周期内存对象
↓
调用结束后不进入任何持久化快照
```

缺少 Credential、解密失败或主密钥未配置时 fail closed，返回配置未就绪；不回退读取
旧环境变量。

---

# 8. 创建模型业务流程

```text
用户点击“添加模型”
↓
填写：
  显示名称
  Base URL
  API Key
  Model Name
  参数
↓
点击“验证连接”
↓
后端通过通用 OpenAI-compatible 适配器请求该模型 API
↓
成功：
  返回连接成功
  尽可能获取模型列表
↓
用户选择/确认模型名称
↓
点击“保存模型”
↓
系统生成 model_uid
↓
保存 Model
↓
API Key 加密保存到 Credential
↓
模型出现在模型列表
```

如果 Provider 不支持列出 `/models`：

允许：

```text
手工输入 model_name
```

作为 fallback。

---

# 9. 多模型

系统必须允许同时保存多个模型。

例如：

```text
Model A
qwen-plus
base_url A

Model B
qwen-max
base_url A

Model C
qwen-plus
base_url B
```

均独立存在。

模型列表不是“版本列表”。

用户看到的是：

```text
模型管理
```

不是：

```text
Model Config Version 管理
```

---

# 10. 默认模型

默认模型不是模型自身属性。

建议单独保存 Runtime 状态：

```text
runtime_model_state
- id = 1
- default_model_id
- updated_at
```

用户可：

```text
设为默认
```

行为：

```text
default_model_id = selected_model_id
```

不创建新模型。

不创建新 Credential。

不要求发布 Release。

---

# 11. 意图识别时切换模型

意图识别请求支持：

```json
{
  "text": "...",
  "model_uid": "mdl_xxx"
}
```

规则：

```text
请求带 model_uid
→ 使用指定模型

请求未带 model_uid
→ 使用系统默认模型
```

前端意图识别页面提供：

```text
使用模型
[ 模型下拉框 ]
```

默认选择系统默认模型。

用户在页面临时选择其他模型：

- 只影响本次 / 当前页面调用；
- 不自动修改系统默认模型。

---

# 12. Runtime 调用链

```text
用户输入
↓
读取 model_uid
↓
有 model_uid：
    获取指定模型
无 model_uid：
    获取默认模型
↓
确认模型 enabled
↓
获取：
    model_name
    base_url
    params
↓
解析 Credential
↓
解密 API Key
↓
调用 Provider
↓
IntentService
↓
PromptBuilder
↓
模型返回
↓
Schema Validate
↓
Business Validate
↓
IntentResult
```

---

# 13. 成功结果落库

成功识别必须落库。

建议新增：

```text
intent_recognition_result
```

字段建议：

```text
id
request_id

model_id
model_uid
model_name
base_url

model_snapshot_json

input_text
context_json

route
intents_json
slots_json
risk_json
need_clarification
clarification_json

latency_ms
input_tokens
output_tokens
total_tokens

provider_request_id

created_at
```

---

# 14. model_snapshot_json

成功结果必须保存本次真实调用的非 Secret 快照。

例如：

```json
{
  "model_uid": "mdl_xxx",
  "model_name": "qwen-plus",
  "base_url": "https://...",
  "params": {
    "temperature": 0.1,
    "top_p": 0.8,
    "timeout_seconds": 30,
    "max_retries": 2
  }
}
```

目的：

以后即使模型参数被编辑，也知道历史调用当时真正使用的参数。

绝对禁止保存 API Key。

---

# 15. 失败调用单独保存

失败调用不进入成功业务表。

建议新增：

```text
intent_recognition_failure
```

字段建议：

```text
id
request_id

model_id
model_uid
model_name
base_url

model_snapshot_json

input_text
context_json

failure_stage
error_type
error_code
error_message

provider_status_code
provider_request_id

retry_count
latency_ms

created_at
```

API Key 绝对禁止进入该表。

---

# 16. failure_stage

统一一张失败表，不按失败类型拆多个表。

通过：

```text
failure_stage
error_type
error_code
```

区分。

建议 failure_stage：

```text
credential
connection
provider_auth
provider_rate_limit
provider_server
model_output
schema_validation
business_validation
internal
```

示例：

```text
credential
- API Key 不存在
- 解密失败

connection
- DNS
- Timeout
- Connect Error

provider_auth
- 401
- 403

provider_rate_limit
- 429

provider_server
- Provider 5xx

model_output
- 返回非 JSON
- 空响应

schema_validation
- JSON 存在，但不符合 IntentResult Schema

business_validation
- Route / Intent / confidence 等业务规则不合法

internal
- AICoach 自身异常
```

---

# 17. 模型编辑规则

核心原则：

> 决定“它是谁”的字段不能编辑；决定“怎么调用它”的字段可以编辑。

---

## 17.1 可以编辑

### display_name

可以编辑。

原因：

- 只是用户显示名称；
- 不影响模型身份。

---

### API Key

可以替换。

行为：

```text
原模型不变
model_uid 不变
历史调用不变
只更新 Credential
```

编辑页不显示真实 Key：

```text
✓ 已配置
••••••••ABCD

[ 更换 API Key ]
```

---

### 模型参数

可以编辑：

```text
temperature
top_p
timeout_seconds
max_retries
max_concurrency
```

参数更新后：

- model_uid 不变；
- 以后调用使用新参数；
- 历史调用依靠 model_snapshot_json 保留旧参数。

---

### enabled

可以启用 / 禁用。

禁用后：

- 不出现在可调用模型列表；
- 新请求不能使用；
- 历史记录继续保留。

---

## 17.2 不可以编辑

### model_name

不可编辑。

修改 model_name = 新模型。

---

### base_url

不可编辑。

修改 base_url = 新模型。

---

### model_uid

绝对不可编辑。

---

### created_at

系统字段，不可编辑。

---

### 验证状态

用户不可直接编辑。

由“测试连接”结果更新。

---

# 18. 修改模型名称 / Base URL

如果用户需要修改：

```text
model_name
或
base_url
```

不允许在原模型上直接修改。

提供：

```text
[ 基于此模型创建新模型 ]
```

行为：

```text
复制：
  display_name
  params

重新填写 / 确认：
  model_name
  base_url
  API Key

保存
↓
生成新的 model_uid
```

原模型继续保留。

---

# 19. API Key 更换流程

```text
编辑模型
↓
API Key
✓ 已配置 ••••ABCD
↓
点击“更换 API Key”
↓
输入新 Key
↓
验证连接
↓
验证成功
↓
保存
↓
更新 Credential
```

不创建新模型。

不创建新 model_uid。

不改变历史调用。

---

# 20. 默认模型与禁用规则

如果模型是当前默认模型：

禁止直接禁用。

提示：

```text
当前模型是默认模型。
请先设置其他默认模型后再禁用。
```

设置新默认模型后：

原默认模型可禁用。

---

# 21. 删除模型

一期不提供物理删除。

只提供：

```text
启用
禁用
```

原因：

- 历史成功结果引用 model_uid；
- 历史失败日志引用 model_uid；
- 避免引入复杂引用完整性处理。

---

# 22. 模型管理页面

导航：

```text
AI Coach

├── 意图识别
└── 模型管理
```

模型管理页：

```text
模型管理

[ + 添加模型 ]

┌──────────────────────────────────────┐
│ 通义千问 Plus                ★ 默认 │
│ qwen-plus                            │
│ DashScope                            │
│ ● 可用                               │
│                                      │
│ [测试连接] [编辑]                    │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ 通义千问 Max                         │
│ qwen-max                             │
│ DashScope                            │
│ ● 可用                               │
│                                      │
│ [测试连接] [编辑] [设为默认]         │
└──────────────────────────────────────┘
```

不显示：

```text
Credential Ref
Version
Hash
Fingerprint
Release ID
Structured Output
```

---

# 23. 添加模型页面

```text
添加模型

显示名称
[ 通义千问 Plus ]

调用地址
[ https://... ]

API Key
[ **************** ]

模型名称
[ qwen-plus ▼ ]

模型参数

Temperature
[ 0.1 ]

Top P
[ 0.8 ]

高级设置 ▼

Timeout
[ 30 ]

Retry
[ 2 ]

[ 验证连接 ]
[ 保存模型 ]
```

---

# 24. 编辑模型页面

```text
编辑模型

基本信息

显示名称
[ 通义千问 Plus ]

模型名称
qwen-plus                  🔒

调用地址
https://.../v1             🔒

模型 ID
mdl_xxxxx                  🔒


连接凭据

API Key
✓ 已配置 ••••••••ABCD

[ 更换 API Key ]
[ 测试连接 ]


模型参数

Temperature
[ 0.1 ]

Top P
[ 0.8 ]

高级设置 ▼

Timeout
[ 30 ]

Retry
[ 2 ]

[ 保存修改 ]


其他操作

[ 禁用模型 ]

需要修改模型名称或调用地址？
[ 基于此模型创建新模型 ]
```

---

# 25. 意图识别页面

```text
意图识别

使用模型
[ 通义千问 Plus · qwen-plus ▼ ]

┌───────────────────────────────────┐
│ 输入需要识别的内容                │
│                                   │
│ 我想找一份北京的后端开发工作      │
│                                   │
└───────────────────────────────────┘

[ 开始识别 ]
```

执行中：

```text
正在识别...
```

结果：

```text
识别结果

一级路由
求职业务
job_search

意图
寻找职位     96%
筛选职位     74%

识别参数
城市         北京
职位         后端开发

风险
无

模型：qwen-plus
耗时：823ms
```

---

# 26. 失败页面

例如认证失败：

```text
识别失败

模型：qwen-plus

模型服务认证失败，请检查 API Key。

[重新识别]
[编辑模型]
```

Timeout：

```text
模型服务响应超时。

[重新识别]
```

禁止直接显示内部异常栈。

---

# 27. Release 与模型的最终关系

当前实现采用以下产品语义：

```text
Business Config
负责：
Route / Intent / Slot / Prompt 等业务规则

Model
负责：
model_name / base_url / params / credential

Runtime Request
负责：
本次实际选择哪个 model_uid
```

因此：

- “切模型”不应该要求用户手工创建 Release；
- “设为默认模型”不应该要求发布 Release；
- Runtime Request 可以显式指定 model_uid；
- Business Release 和 Model Runtime Selection 已完全解耦；
- Release 只冻结业务规则，Runtime 使用请求指定的 `model_uid`，未指定时使用
  `runtime_model_state.default_model_id`。

---

# 28. 实现限制

当前实现限制：

- 把 API Key 写入 ModelConfig；
- 把 API Key 写进 Trace；
- 把 model_name / base_url 做成可编辑；
- 把默认模型做成 Model 自身不可变属性；
- 增加多 Credential；
- 增加 Load Balancing；
- 增加 RBAC；
- 扩大到批量评测、Replay、Trace UI。

---

# 29. 数据库迁移原则

允许新增：

```text
provider_credential
model / model_endpoint（若采用新模型实体）
runtime_model_state
intent_recognition_result
intent_recognition_failure
```

已确认采用破坏性迁移：

- 删除 `model_config` 表和旧模型 Provider/API；
- 删除依赖旧 ModelConfig 语义的 Release、Trace、Evaluation 历史数据；
- 删除 `managed_model.credential_ref` 环境变量兼容支路，仅保留加密 Credential；
- 保留 `config_draft` 和已经使用加密凭据的 ManagedModel；
- 该迁移不提供 downgrade，恢复只能依赖部署前备份。

---

# 30. 当前用户已确认的业务规则

以下视为已审批：

1. 系统需要记住每次意图识别实际使用的模型；
2. 模型身份由 `model_name + base_url` 决定；
3. API Key 不参与模型身份；
4. 系统允许保存多个模型；
5. 调用时允许切换模型；
6. 请求可指定 model_uid；
7. 未指定时使用默认模型；
8. 成功数据单独落库；
9. 失败调用单独落失败日志；
10. API Key 跟随创建模型时一起输入；
11. API Key 可以后续替换；
12. model_name / base_url 创建后不可编辑；
13. 修改 model_name / base_url 必须创建新模型；
14. display_name 可以编辑；
15. 模型调用参数可以编辑；
16. 历史调用必须保存当时的模型参数快照；
17. 默认模型可以切换；
18. 默认模型不能直接禁用；
19. 一期不物理删除模型；
20. 用户界面不暴露 Credential Ref / Version / Hash / Fingerprint / Release。
21. 用户界面不提供 Provider/厂商选择；一期统一接入 OpenAI-compatible API。
22. Qwen、DeepSeek 等具体服务由用户填写的 Base URL、API Key、Model Name 决定。

---

# 31. 当前执行 Gate

Release 解耦、旧 ModelConfig 删除和不可逆迁移已获用户确认。仍需单独确认的事项：

- 执行数据库迁移；
- 执行任何测试；
- 新增超出本设计的 Credential 能力；
- 改变 model_uid 定义或成功/失败落库边界。
