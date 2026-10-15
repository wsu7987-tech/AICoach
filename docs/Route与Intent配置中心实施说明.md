# Route 与 Intent 配置中心实施说明

更新时间：2026-10-14

## 最终设计

配置中心保存结构化数据，`PromptBuilder` 在模型调用前将有效配置转换成普通文本。配置 JSON 是存储和接口传输格式，不是模型提示词格式。

模型实际收到两条消息：

- `system`：任务说明、识别规则、Route 文本模块、Intent 文本模块、Slot 文本模块和输出要求。
- `user`：上下文（如有）和用户输入。

结构化 JSON 只用于模型输出：`LLMProvider` 通过 `response_format` 要求模型按 `json_schema` 或 `json_object` 返回识别结果。输入提示词与输出约束是两件事。

## Route 模块

Route 管理支持新增、编辑和删除。删除包含子 Intent 的 Route 时，会在二次确认后级联删除其下 Intent 和相关典型说法；配置至少保留一个 Route。运行时只把已启用 Route 的以下内容写入提示词：

```text
## 可选 Route

从以下 Route 中选择一个：

- training_business：用户希望开始、继续或执行训练相关业务
- information_query：查询用户自身训练、身体状态、恢复、计划或历史信息
```

字段作用：

- `name`：模型必须返回的 Route 标识。
- `description`：告诉模型该 Route 覆盖什么语义。
- `enabled`：只控制是否参与提示词生成，本身不发给模型。
- `zh`：只用于配置后台显示，本身不发给模型。

页面“提示词预览”只显示 Route 模块，不再显示完整 Prompt，也不显示配置 JSON。

## Intent 模块

Intent 管理采用 Element Plus `el-tree` 呈现“Route 父节点 → Intent 子节点”，右侧编辑详情，维护标识、显示名称、所属 Route、说明和典型用户说法。Route 节点可直接新增 Intent，Intent 节点可删除；搜索使用树节点过滤。单个 Intent 的提示词预览入口位于右侧详情区。运行时按 Route 分组生成：

```text
## 二级 Intent

### Route: training_business

- start_training：开始一次新的训练
  典型说法：
  - 开始训练
  - 我要练胸
```

字段作用：

- `name`：模型必须返回的 Intent 标识。
- `route`：限定 Intent 所属的一级分类。
- `description`：告诉模型该 Intent 的语义边界。
- 典型用户说法：提供该 Intent 的表达示例。
- `enabled`：只控制是否参与提示词生成，本身不发给模型。
- `zh`：只用于配置后台显示，本身不发给模型。
- `mapping_note`：配置维护信息，不发给模型。

Intent 页面顶部“全部 Intent 提示词预览”显示所有已启用 Intent 的完整模块；右侧详情区的“单个 Intent 提示词预览”只显示当前已保存的 Intent。Route 页面保留独立的 Route 提示词预览。页面预览与运行时共用同一个后端渲染函数，避免“预览一种内容、实际调用另一种内容”。

## GitHub 实现依据

### lastmile-ai/mcp-agent

- 参考文件：<https://github.com/lastmile-ai/mcp-agent/blob/main/src/mcp_agent/workflows/intent_classifier/intent_classifier_llm.py>
- 证据：`_generate_context()` 将每个 Intent 渲染为 `Intent: {name}`、`Description: {description}` 和 `Examples` 的普通文本；模型调用再通过 `generate_structured(..., strict=True)` 单独约束结构化输出。
- 本项目采用：Prompt 输入使用名称、说明、示例组成的普通文本；结构化 JSON 仅用于输出约束。
- 未采用：其 MCP Agent 工作流、路由执行机制和依赖体系。

### openziti/llm-gateway

- 参考文档：<https://github.com/openziti/llm-gateway/blob/main/docs/current/semantic-routing.md>
- 证据：Route 配置包含 `name / description / examples`；文档明确 `name` 是标识和分类结果，`description` 会进入分类器 Prompt，帮助 LLM 理解 Route。
- 本项目采用：Route 提示词只保留用于分类输出的标识和帮助模型理解范围的说明。
- 未采用：其 embedding 路由、网关架构和 Route 业务分类。

### Rasa

- 参考文件：<https://github.com/RasaHQ/rasa/blob/3.6.x/docs/docs/training-data-format.mdx>
- 证据：NLU 数据按 Intent 组织用户表达，一个 Intent 对应一组 examples。
- 本项目采用：Intent 与典型用户说法一并维护，并在提示词中按 Route、Intent 分组。
- 未采用：Rasa Runtime、训练管线、实体语法和模型体系。

## 本次修改文件

- `backend/app/prompting/builder.py`：将运行时 Prompt 从配置 JSON 改为确定性的普通文本；增加 Route 和单 Intent 模块渲染。
- `backend/app/schemas/config.py`：增加模块预览请求与响应结构。
- `backend/app/services/config_service.py`：增加模块预览服务，并复用运行时渲染器。
- `backend/app/api/admin/config.py`：增加 `/config/prompt-preview/module` 接口。
- `frontend/src/configApi.ts`：增加模块预览调用。
- `frontend/src/ConfigCenter.vue`：Route 增加级联删除；Intent 使用树组件管理新增和删除，并区分全部 Intent 预览与右侧单 Intent 预览。
- `frontend/src/config-center.css`：增加树节点和普通文本 Prompt 预览样式。

## 测试状态

按用户明确要求，本次没有执行测试、构建、Lint、格式化检查、类型检查或 E2E。以上修改尚未经过命令验证。
