# Intent 必填参数与默认值设计

## 目标

在复用现有 Slot 定义的前提下，让每个 Intent 声明自己的必填参数，并为参数选择性配置默认值。

- 用户提供参数：采用提取结果。
- 用户未提供、配置了默认值：程序补入默认值，不因该参数追问。
- 用户未提供、未配置默认值：程序强制 `need_clarification=true` 并生成缺参提示。
- V1 以 Top-1 Intent 为准；V2 对每个 action 的 Intent 分别执行。

## 配置模型

Intent 新增兼容字段：

```json
{
  "name": "volume_up",
  "required_slots": [
    { "slot_name": "volume_delta", "default_value": "10" }
  ]
}
```

`slot_name` 必须引用已启用 Slot，同一个 Intent 内不能重复。枚举 Slot 的默认值必须是已启用的 canonical；文本 Slot 的默认值保存为字符串。旧配置没有该字段时按空列表处理，因此不需要数据库迁移或提升顶层 `schema_version`。

当前契约规定 `training_business` 不能返回澄清问题，所以训练类 Intent 的必填参数必须配置默认值。

## 数据流

```text
Intent + required_slots 配置
            │
            ├── Prompt：告诉模型哪些参数必填、缺失时默认或追问
            │
用户文本 ──► Slot 提取（LLM 文本 + 程序枚举）
                         │
                         ▼
                 Top-1 Intent / action 校验
                    ┌────┴────┐
              已有参数       缺少参数
                 │        ┌────┴────┐
                 │      有默认值    无默认值
                 │         │          │
                 └────────►补值       └──►强制澄清
```

默认值生成的 `SlotValue` 使用 `start=0`、`end=0`、`confidence=1`，表示它不是用户原文中的 span；Trace 同时记录 `REQUIRED_SLOT_DEFAULT_APPLIED`。缺少且无默认值记录 `REQUIRED_SLOT_MISSING`。

## 管理界面

`/config/intents` 的 Intent 编辑区维护必填参数：

- 从已启用 Slot 中选择参数；
- 文本 Slot 可输入默认值；
- 枚举 Slot 只能选择启用的 canonical；
- 被引用的 Slot 不能停用或删除；
- Slot 重命名时同步更新 Intent 引用。

## 边界与后续演进

当前实现只校验本次请求提取到的参数，不从历史对话或 `context` 自动继承参数。若后续要支持“先追问、下一轮只回答数值”的完整槽位填充，应增加会话级 pending action/slot 状态，并定义过期、覆盖和并发请求规则。默认值目前统一为字符串，以保持 Runtime Slot 契约不变；若下游需要数值或时间范围的强类型校验，再为 Slot 增加类型约束和解析器。
