# TASK-201 在线配置与 Release

## 依赖

TASK-102

## 阅读

- `docs/03-Intent路由与动态Prompt设计.md`
- `docs/07-数据库与配置版本设计.md`
- `docs/04-后台页面与交互设计.md`

## 目标

提供生产可用但简洁的在线配置：一个 JSON Draft + Model Config versions + immutable Release。

## 后端

实现：

- Draft read/update
- Draft schema/business validation
- Prompt preview
- Model Config create/list/disable；已被引用版本不可原地修改
- Publish：请求显式传入 `default_model_config_id`（必填、必须 enabled）；生成 canonical snapshot + `config_snapshot_hash`，计算 `model_config_hash` 与 `release_fingerprint`，事务切换 Active Release
- Validate/Publish 拒绝：routes 不是固定 7 个或存在 disabled Route；二级 Intent 所属 route 不存在；name/zh/alias 在整个 intents 内冲突（同名、同中文名或别名指向多个 Intent）
- Release list/detail/history
- historical release -> create draft

无需实现复杂字段级版本树；需要提供人类可读的发布前 summary/diff（JSON section-level 即可）。

## 前端

配置中心保留 Tabs：

- Route
- Intent
- Slot
- Enum/Alias
- Prompt Template
- Model Config
- Release

UI 操作 Draft JSON 的对应 section；研发不直接编辑数据库。

必须有：

- Save Draft
- Validate
- Prompt Preview
- Publish confirmation
- Release History
- 从历史 Release 创建 Draft/重新发布

## Bootstrap

首次打开若 Draft 空，可提示导入 bootstrap；不得自动发布。

## 测试

- invalid reference / duplicate name
- publish transaction
- immutable historical release
- model config immutability after use
- snapshot/hash deterministic
- create draft from old release
- Draft edit 不影响 Active Runtime

## DoD

无需改代码/YAML 即可维护业务配置；历史运行配置可准确恢复。

## 快速 Intent 调整验收（本 Task 范围）

本 Task 必须证明不改 Python 代码即可完成：
1. 新增一个二级 Intent；
2. 增加 alias/Few-shot/Slot 枚举；
3. Validate + Prompt Preview；
4. Publish 新 Release，Active 切换且历史 Release 不变。

以下两步依赖后续 Task，**不在本 Task 验收**，由后续 Task 完成：
- 跑小规模回归 Evaluation → TASK-301 验收，并在 TASK-501 E2E #19 端到端复验；
- Runtime 在 cache refresh 后使用新 Release → TASK-103 验收，并在 TASK-501 E2E #19 复验。

一级 Route key 不允许通过配置新增/删除/改名/disable；Validate/Publish 必须拒绝。
