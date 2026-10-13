# TASK-201：0003 存量审计与恢复

本流程适用于 MySQL 8；也适用于已经标记 `0003_model_timeout_double` 的数据库。Alembic head 只说明迁移版本，不能证明历史 Hash 可重建。修复后的 `alembic/env.py` 每次在线执行都先审计现存配置（即使 upgrade 无版本变化），0003 自身也在任何 DDL 前再次审计。没有新增 Schema，因此 head 仍为 0003。

## 执行前提

1. 使用维护窗口停止所有配置写入方、脚本及其他迁移进程，排空事务；数据库维护账号与应用账号分离。不能只停一个 Pod。
2. 备份原库、Schema、alembic_version、相关配置/Release/Trace/Evaluation 记录及可用原始配置，验证备份可恢复；保留访问限制，不把 Secret 导出到日志。
3. 在隔离克隆库先运行下面的审计/升级/再审计。生产库未在 TASK-201 修复测试中访问，其实际损坏分布仍 UNVERIFIED。

MySQL 的 ALTER TABLE 会隐式提交，atomic DDL 仅保证一条支持的 DDL 原子完成，不保证整个迁移事务回滚。因此审计与 DDL 之间必须由上述停写措施保护；审计程序本身不是在线并发写入屏障。[隐式提交](https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html)、[Atomic DDL](https://dev.mysql.com/doc/refman/8.0/en/atomic-ddl.html)。

## 只读审计与升级

由部署 Secret 安全配置 DATABASE_URL，在 `backend/` 执行，逐条检查退出码，任一步非零立即停止：

```text
uv run --locked --extra dev python -m app.db.config_audit
uv run --locked --extra dev alembic upgrade head
uv run --locked --extra dev python -m app.db.config_audit
```

空库首次部署没有存量，先 migration，再运行审计。已有库审计成功输出 `{"status":"PASS","models":N,"releases":M}`。失败为 `CONFIG_AUDIT_FAILED`，只列行 ID 与错误类别，不输出配置值：

- `MODEL_HASH_OR_PAYLOAD`：正式 ModelConfigCreate 校验或 canonical runtime hash 不符，包括未被引用/disabled 历史版本。
- `RELEASE_HASH_OR_REFERENCE`：Business Snapshot、Business Hash、引用 Model、冻结 Model Hash 或 Fingerprint 不符。
- `ACTIVE_REFERENCE`：Active 指向无法验证的 Release，或其 Model disabled。

程序没有 UPDATE/INSERT/DELETE，不改任何 Hash 或 Fingerprint。重复运行结果应一致。已处于 0003 head 的损坏库也会非零退出，不能以 `alembic current` 或 `/ready` 通过替代审计。离线 0003 upgrade 被拒绝，不能用生成 SQL 绕过数据审计；不得 `alembic stamp head` 跳过。

## 中断恢复

| 检查到的状态 | 处理 |
|---|---|
| 审计失败、尚未执行 DDL | 保持当前 revision，执行下述数据处理；重复 upgrade 仍应拒绝 |
| FLOAT 原列 + nullable timeout_seconds_upgrade | 停写并重新审计，通过后重跑 upgrade；重新从原列文本复制，覆盖未完成临时值 |
| 原子 DROP/CHANGE 已完成为 DOUBLE，但 revision 仍 0002 | 停写并重新审计；通过后 0003 识别 DOUBLE，不再改列，然后更新 revision |
| 已 0003 | 每次在线 migration 入口仍审计；独立命令也可直接复核 |

不要手工删除原列/临时列，不要手工标记 revision。保留故障现场和备份。降级仍受 DOUBLE→FLOAT 有损检查保护；审计失败也会阻止在线 downgrade。恢复备份属于运维变更，不能通过修改 Hash 使检查变绿。

## 无法重建的 FLOAT 历史记录

`30.123456789` 存入旧 FLOAT 后可能读回 `30.1235`，仅凭这个值与 SHA256 无法恢复原值。迁移不会猜测、舍入后重签、覆盖历史 Model Hash 或 Release Fingerprint。

1. 保留损坏库只读副本和审计失败行清单，核对原始配置、已冻结快照及备份的可信来源；是否存在有效来源由人工确认。
2. 优先从经审计通过的完整备份恢复到隔离库，再验证升级。不能把另一个同样发生 FLOAT 损失的备份当作已恢复。
3. 没有可审计的完整备份时，该库的原地升级保持 **BLOCKED**。仅创建替代 Model/Release 不能让全量历史审计通过；不要删除坏行、修改旧 Release、覆盖旧 Hash，或只改 Active 指针绕过。
4. 如需恢复业务，由运维/业务负责人另行审批迁移到新的干净数据库：保留旧库只读作为历史审计档案；以经确认的原始业务配置显式导入新 Draft，创建新 Model 版本，Validate/Preview/审阅后发布新 Release，并独立验证调用。新库使用独立来源标识，不把旧 ID 映射成同一历史身份；Trace/Evaluation 历史引用保留在原档案。此流程是新发布，不是修复或重写旧历史。

本 Task 仅提供上述处理流程与受控故障回归，不自动执行生产恢复或数据迁移，不声称真实 Qwen/生产启用已验收。
