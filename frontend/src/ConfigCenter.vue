<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref } from "vue";
import { ElMessageBox } from "element-plus";
import bootstrap from "../../bootstrap/initial-config.v1.json";
import {
  configApi,
  ConfigApiError,
  type Draft,
  type DraftJson,
  type ModelConfig,
  type ModelInput,
  type PublishSummary,
  type Release,
  type Route,
  type FieldIssue,
} from "./configApi";

const tab = ref("routes");
const busy = ref(false);
const loaded = ref(false);
const dirty = ref(false);
const draft = ref<Draft>({
  draft_json: null,
  draft_hash: null,
  updated_at: null,
});
const routes = ref<Route[]>([]);
const editors = reactive({
  intents: "[]",
  slots: "[]",
  enums: "{}",
  examples: "[]",
  prompt_template: "{}",
});
const models = ref<ModelConfig[]>([]);
const releases = ref<Release[]>([]);
const releaseOffset = ref(0);
const activeId = ref<number | null>(null);
const selectedModel = ref<number>();
const message = ref("");
const error = ref("");
const issues = ref<FieldIssue[]>([]);
const previewText = ref("你好");
const preview = ref("");
const previewVisible = ref(false);
const summary = ref<PublishSummary>();
const confirmVisible = ref(false);
const note = ref("");
const detail = ref<Release>();
const detailVisible = ref(false);
const paramsText = ref('{"temperature": 0}');
const modelForm = reactive<ModelInput>({
  name: "Qwen",
  version: "1",
  provider: "qwen",
  model: "qwen-plus",
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  params_json: {},
  timeout_seconds: 30,
  max_retries: 1,
  max_concurrency: 4,
  structured_output_mode: "json_object",
  credential_ref: "DASHSCOPE_API_KEY",
});
const pretty = (value: unknown) => JSON.stringify(value, null, 2);

async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  issues.value = [];
  message.value = "";
  try {
    await action();
  } catch (e) {
    if (e !== "cancel" && e !== "close") {
      error.value = e instanceof Error ? e.message : String(e);
      if (e instanceof ConfigApiError) issues.value = e.issues;
    }
  } finally {
    busy.value = false;
  }
}
function acceptDraft(value: Draft) {
  draft.value = value;
  if (value.draft_json) {
    routes.value = structuredClone(value.draft_json.routes);
    for (const key of Object.keys(editors) as (keyof typeof editors)[])
      editors[key] = pretty(value.draft_json[key]);
  }
  dirty.value = false;
  summary.value = undefined;
}
function draftPayload(): DraftJson {
  const result: Record<string, unknown> = {
    schema_version: 1,
    routes: routes.value,
  };
  for (const key of Object.keys(editors) as (keyof typeof editors)[]) {
    try {
      result[key] = JSON.parse(editors[key]);
    } catch {
      throw new Error(`${key}：JSON 格式错误，请检查引号、逗号和括号`);
    }
  }
  return result as unknown as DraftJson;
}
async function loadModels() {
  const rows: ModelConfig[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await configApi.models(offset);
    rows.push(...page);
    if (page.length < 200) break;
  }
  models.value = rows;
}
async function loadHistory() {
  const history = await configApi.releases(releaseOffset.value);
  releases.value = history.items;
  activeId.value = history.active_release_id;
}
async function reload() {
  await run(async () => {
    if (dirty.value)
      await ElMessageBox.confirm(
        "重新载入会丢弃本地未保存编辑，是否继续？",
        "重新载入",
      );
    const value = await configApi.draft();
    await Promise.all([loadModels(), loadHistory()]);
    acceptDraft(value);
    loaded.value = true;
  });
}
async function save() {
  await run(async () => {
    acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
    message.value = "Draft 已保存，Active Release 未改变";
  });
}
async function validate() {
  await run(async () => {
    await configApi.validate();
    message.value = "校验通过：Schema、七个 Route、名称/别名与引用合法";
  });
}
async function showPreview() {
  await run(async () => {
    const value = await configApi.preview(previewText.value);
    preview.value = value.final_prompt;
    previewVisible.value = true;
  });
}
async function importBootstrap() {
  await run(async () => {
    acceptDraft(await configApi.bootstrap(bootstrap as DraftJson));
    message.value =
      "Bootstrap 已导入 Draft，请确认业务配置后创建模型版本并发布";
  });
}
async function createModel() {
  await run(async () => {
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText.value);
    } catch {
      throw new Error("模型参数 JSON 格式错误");
    }
    const model = await configApi.createModel({
      ...modelForm,
      params_json: params,
    });
    await loadModels();
    selectedModel.value = model.id;
    message.value = `已创建 ${model.name} / ${model.version}`;
  });
}
function copyModel(model: ModelConfig) {
  for (const key of Object.keys(modelForm) as (keyof ModelInput)[])
    Object.assign(modelForm, { [key]: model[key] });
  modelForm.version = `${model.version}-next`;
  paramsText.value = pretty(model.params_json);
  message.value = "已复制参数，请填写新版本号后创建";
}
async function disableModel(model: ModelConfig) {
  await run(async () => {
    await ElMessageBox.confirm(
      `禁用 ${model.name} / ${model.version}？历史记录会保留。`,
      "禁用模型版本",
    );
    await configApi.disableModel(model.id);
    await loadModels();
    if (selectedModel.value === model.id) selectedModel.value = undefined;
    message.value = "模型版本已禁用";
  });
}
async function preparePublish() {
  await run(async () => {
    if (!selectedModel.value) throw new Error("请选择一个启用的 Model Config");
    summary.value = await configApi.summary(selectedModel.value);
    note.value = "";
    confirmVisible.value = true;
  });
}
async function publish() {
  await run(async () => {
    if (!summary.value || !note.value.trim()) throw new Error("请填写发布说明");
    const result = await configApi.publish(summary.value, note.value);
    confirmVisible.value = false;
    releaseOffset.value = 0;
    await loadHistory();
    message.value = `Release #${result.id} 已发布并激活`;
  });
}
async function showRelease(row: Release) {
  await run(async () => {
    detail.value = await configApi.release(row.id);
    detailVisible.value = true;
  });
}
async function restore(row: Release) {
  await run(async () => {
    await ElMessageBox.confirm(
      `使用 Release #${row.id} 的历史配置替换当前 Draft？${dirty.value ? "本地未保存编辑会丢弃。" : ""}随后需重新发布才能生效。`,
      "从历史 Release 创建 Draft",
    );
    acceptDraft(await configApi.restore(row.id, draft.value.draft_hash));
    message.value = `已从 Release #${row.id} 创建 Draft，请校验、预览并重新发布`;
  });
}
async function pageHistory(delta: number) {
  await run(async () => {
    releaseOffset.value += delta;
    await loadHistory();
  });
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  void reload();
});
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
</script>

<template>
  <section class="config-center" v-loading="busy">
    <div class="config-heading">
      <div>
        <h2>配置中心</h2>
        <p>编辑 Draft → 校验 → Prompt 预览 → 发布新 Release</p>
      </div>
      <el-button @click="reload" :disabled="busy">重新载入</el-button>
    </div>
    <el-alert
      v-if="error"
      type="error"
      :title="error"
      :closable="false"
      role="alert"
      ><ul v-if="issues.length">
        <li v-for="(issue, i) in issues" :key="i">
          {{ issue.field }}：{{ issue.message }}
        </li>
      </ul></el-alert
    >
    <el-alert
      v-if="message"
      type="success"
      :title="message"
      :closable="false"
      role="status"
    />
    <el-alert
      v-if="dirty"
      title="有未保存修改，请先保存，再执行校验、预览或发布。"
      type="warning"
      :closable="false"
    />
    <el-card
      v-if="loaded && !draft.draft_json"
      class="bootstrap-card"
      shadow="never"
      ><h3>创建第一份 Draft</h3>
      <p>从项目 Bootstrap 导入初始业务配置，确认后再发布。</p>
      <el-button type="primary" @click="importBootstrap" :disabled="busy"
        >导入 Bootstrap 到 Draft</el-button
      ></el-card
    >
    <div v-if="draft.draft_json" class="toolbar">
      <el-button type="primary" @click="save" :disabled="busy || !dirty"
        >保存 Draft</el-button
      >
      <el-button @click="validate" :disabled="busy || dirty">校验</el-button>
      <el-input
        v-model="previewText"
        aria-label="Prompt 预览输入"
        placeholder="输入预览文本"
        class="preview-input"
      />
      <el-button
        @click="showPreview"
        :disabled="busy || dirty || !previewText.trim()"
        >Prompt 预览</el-button
      >
      <el-tag :type="dirty ? 'warning' : 'info'">{{
        dirty ? "未保存" : "Draft 已同步"
      }}</el-tag>
    </div>
    <el-tabs v-model="tab">
      <el-tab-pane label="Route" name="routes"
        ><p>一级 Route 固定为以下七个且始终启用，可编辑中文名和描述。</p>
        <div v-for="route in routes" :key="route.name" class="route-row">
          <strong>{{ route.name }}</strong
          ><el-input
            v-model="route.zh"
            :aria-label="`${route.name} 中文名`"
            @input="dirty = true"
          /><el-input
            v-model="route.description"
            :aria-label="`${route.name} 描述`"
            @input="dirty = true"
          /></div
      ></el-tab-pane>
      <el-tab-pane label="Intent" name="intents"
        ><template v-if="draft.draft_json"
          ><p>
            编辑 name / zh / route / description / enabled /
            aliases。名称和别名必须在全部 Intent 中无歧义。
          </p>
          <label for="intents-editor">Intents JSON</label
          ><el-input
            id="intents-editor"
            v-model="editors.intents"
            type="textarea"
            :rows="18"
            @input="dirty = true" /><label for="examples-editor"
            >Few-shot Examples JSON（text / route / intent / enabled）</label
          ><el-input
            id="examples-editor"
            v-model="editors.examples"
            type="textarea"
            :rows="10"
            @input="dirty = true" /></template
      ></el-tab-pane>
      <el-tab-pane label="Slot" name="slots"
        ><template v-if="draft.draft_json"
          ><p>
            枚举槽位指定 value_type=enum 和已有 enum_group；字符串槽位指定
            value_type=string。
          </p>
          <el-input
            aria-label="Slots JSON"
            v-model="editors.slots"
            type="textarea"
            :rows="22"
            @input="dirty = true" /></template
      ></el-tab-pane>
      <el-tab-pane label="Enum/Alias" name="enums"
        ><template v-if="draft.draft_json"
          ><p>
            按枚举组编辑 canonical / display / aliases / enabled；Intent 别名在
            Intent 标签维护。
          </p>
          <el-input
            aria-label="Enums JSON"
            v-model="editors.enums"
            type="textarea"
            :rows="22"
            @input="dirty = true" /></template
      ></el-tab-pane>
      <el-tab-pane label="Prompt Template" name="prompt_template"
        ><template v-if="draft.draft_json"
          ><p>编辑 system 和 rules，预览完整 Prompt。</p>
          <el-input
            aria-label="Prompt Template JSON"
            v-model="editors.prompt_template"
            type="textarea"
            :rows="22"
            @input="dirty = true" /></template
      ></el-tab-pane>
      <el-tab-pane label="Model Config" name="models">
        <p>
          每次调整创建新版本。credential_ref 只填后端环境变量名，不能填写 API
          Key。
        </p>
        <el-form
          label-position="top"
          class="model-form"
          @submit.prevent="createModel"
        >
          <el-form-item label="名称"
            ><el-input
              v-model="modelForm.name"
              aria-label="模型配置名称" /></el-form-item
          ><el-form-item label="版本"
            ><el-input v-model="modelForm.version" aria-label="模型配置版本"
          /></el-form-item>
          <el-form-item label="模型"
            ><el-input
              v-model="modelForm.model"
              aria-label="模型名称" /></el-form-item
          ><el-form-item label="Base URL"
            ><el-input v-model="modelForm.base_url" aria-label="Base URL"
          /></el-form-item>
          <el-form-item label="Credential Ref"
            ><el-input
              v-model="modelForm.credential_ref"
              aria-label="Credential Ref" /></el-form-item
          ><el-form-item label="Structured Output"
            ><el-select
              v-model="modelForm.structured_output_mode"
              aria-label="Structured Output"
              ><el-option
                label="json_schema (strict)"
                value="json_schema" /><el-option
                label="json_object"
                value="json_object" /></el-select
          ></el-form-item>
          <el-form-item label="超时（秒）"
            ><el-input-number
              v-model="modelForm.timeout_seconds"
              :min="0.1"
              :step="0.1"
              :max="600" /></el-form-item
          ><el-form-item label="额外重试次数"
            ><el-input-number
              v-model="modelForm.max_retries"
              :min="0"
              :max="5" /></el-form-item
          ><el-form-item label="并发上限"
            ><el-input-number
              v-model="modelForm.max_concurrency"
              :min="1"
              :max="256"
          /></el-form-item>
          <el-form-item label="调用参数 JSON" class="full-width"
            ><el-input
              aria-label="模型参数 JSON"
              v-model="paramsText"
              type="textarea"
              :rows="3"
            /><small
              >支持 temperature / top_p / seed / presence_penalty /
              frequency_penalty。max_tokens 仅可为空。</small
            ></el-form-item
          >
          <el-button type="primary" native-type="submit" :disabled="busy"
            >创建模型版本</el-button
          >
        </el-form>
        <el-table :data="models" row-key="id"
          ><el-table-column prop="id" label="ID" width="70" /><el-table-column
            prop="name"
            label="名称"
          /><el-table-column prop="version" label="版本" /><el-table-column
            prop="model"
            label="模型"
          /><el-table-column label="状态"
            ><template #default="{ row }">{{
              row.enabled ? "启用" : "禁用"
            }}</template></el-table-column
          ><el-table-column label="操作" width="230"
            ><template #default="{ row }"
              ><el-button @click="copyModel(row)" :disabled="busy"
                >复制为新版本</el-button
              ><el-button
                @click="disableModel(row)"
                :disabled="busy || !row.enabled"
                >禁用</el-button
              ></template
            ></el-table-column
          ></el-table
        >
      </el-tab-pane>
      <el-tab-pane label="Release" name="releases">
        <p>
          Active Release：{{
            activeId ? `#${activeId}` : "尚未发布"
          }}。回退需从历史创建 Draft 后重新发布。
        </p>
        <div class="toolbar">
          <el-select
            v-model="selectedModel"
            aria-label="发布模型版本"
            placeholder="选择启用的 Model Config"
            class="model-select"
            ><el-option
              v-for="model in models.filter((m) => m.enabled)"
              :key="model.id"
              :label="`${model.name} / ${model.version} (#${model.id})`"
              :value="model.id" /></el-select
          ><el-button
            type="primary"
            @click="preparePublish"
            :disabled="busy || dirty || !draft.draft_json || !selectedModel"
            >查看发布摘要</el-button
          >
        </div>
        <el-table :data="releases" row-key="id"
          ><el-table-column label="Release" width="140"
            ><template #default="{ row }"
              >#{{ row.id }}
              <el-tag v-if="row.id === activeId" type="success"
                >Active</el-tag
              ></template
            ></el-table-column
          ><el-table-column
            prop="created_at"
            label="创建时间 (UTC)"
          /><el-table-column prop="note" label="发布说明" /><el-table-column
            prop="default_model_config_id"
            label="Model ID"
            width="100"
          /><el-table-column label="操作" width="270"
            ><template #default="{ row }"
              ><el-button @click="showRelease(row)" :disabled="busy"
                >详情</el-button
              ><el-button @click="restore(row)" :disabled="busy"
                >从此版本创建 Draft</el-button
              ></template
            ></el-table-column
          ></el-table
        >
        <div class="toolbar">
          <el-button
            @click="pageHistory(-20)"
            :disabled="busy || releaseOffset === 0"
            >上一页</el-button
          ><span>第 {{ releaseOffset / 20 + 1 }} 页</span
          ><el-button
            @click="pageHistory(20)"
            :disabled="busy || releases.length < 20"
            >下一页</el-button
          >
        </div>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="previewVisible" title="Prompt 预览" width="85%">
      <pre class="json-view">{{ preview }}</pre>
    </el-dialog>
    <el-dialog v-model="detailVisible" title="Release 详情" width="85%">
      <pre class="json-view">{{ pretty(detail) }}</pre>
    </el-dialog>
    <el-dialog
      v-model="confirmVisible"
      title="确认发布新 Release"
      width="85%"
      :close-on-click-modal="false"
    >
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="summary"
        ><p>
          基于 Active #{{ summary.active_release_id ?? "无" }}；模型版本 #{{
            summary.default_model_config_id
          }}（{{ summary.model_changed ? "已更换" : "未更换" }}）
        </p>
        <p>
          变更分区：{{
            summary.changes.map((c) => c.section).join("、") ||
            "无业务变更，仍将创建新 Release"
          }}
        </p>
        <p class="hash">
          Snapshot：{{ summary.config_snapshot_hash }}<br />Fingerprint：{{
            summary.release_fingerprint
          }}
        </p>
        <el-collapse
          ><el-collapse-item
            v-for="change in summary.changes"
            :key="change.section"
            :title="change.section"
            ><div class="diff-grid">
              <div>
                <strong>发布前</strong>
                <pre class="json-view">{{ pretty(change.before) }}</pre>
              </div>
              <div>
                <strong>发布后</strong>
                <pre class="json-view">{{ pretty(change.after) }}</pre>
              </div>
            </div></el-collapse-item
          ></el-collapse
        ><el-input
          v-model="note"
          aria-label="发布说明"
          placeholder="填写本次发布说明（必填）"
          maxlength="4000"
          type="textarea"
      /></template>
      <template #footer
        ><el-button @click="confirmVisible = false" :disabled="busy"
          >取消</el-button
        ><el-button
          type="primary"
          @click="publish"
          :disabled="busy || !note.trim()"
          >确认发布并激活</el-button
        ></template
      >
    </el-dialog>
  </section>
</template>
