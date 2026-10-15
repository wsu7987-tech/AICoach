<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch,
} from "vue";
import { ElMessageBox, type TreeInstance } from "element-plus";
import bootstrap from "../../bootstrap/initial-config.v1.json";
import {
  configApi,
  ConfigApiError,
  type Draft,
  type DraftJson,
  type Example,
  type Intent,
  type ModelConfig,
  type PublishSummary,
  type Release,
  type Route,
  type FieldIssue,
} from "./configApi";

const props = defineProps<{ section?: string }>();

const busy = ref(false);
const loaded = ref(false);
const dirty = ref(false);
const draft = ref<Draft>({
  draft_json: null,
  draft_hash: null,
  updated_at: null,
});
const routes = ref<Route[]>([]);
const intents = ref<Intent[]>([]);
const examples = ref<Example[]>([]);
const editors = reactive({
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
const previewTitle = ref("Prompt 预览");
const previewVisible = ref(false);
const summary = ref<PublishSummary>();
const confirmVisible = ref(false);
const note = ref("");
const detail = ref<Release>();
const detailVisible = ref(false);
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const isPromptConfigSection = computed(
  () => props.section === "routes" || props.section === "intents",
);

const routeDialogVisible = ref(false);
const editingRouteName = ref<string | null>(null);
const routeForm = reactive<Route>({
  name: "",
  zh: "",
  description: "",
  enabled: true,
});

type IntentEditor = Intent & { utterances: string[] };
type IntentTreeNode = {
  key: string;
  kind: "route" | "intent";
  label: string;
  caption: string;
  searchText: string;
  routeName: string;
  intentName?: string;
  children?: IntentTreeNode[];
};

const intentSearch = ref("");
const intentTreeRef = ref<TreeInstance>();
const selectedIntentName = ref<string | null>(null);
const isNewIntent = ref(false);
const utteranceInput = ref("");
const intentForm = reactive<IntentEditor>({
  name: "",
  zh: "",
  route: "",
  description: "",
  enabled: true,
  aliases: [],
  mapping_note: null,
  utterances: [],
});

const routeNodeKey = (name: string) => `route:${name}`;
const intentNodeKey = (name: string) => `intent:${name}`;

const intentTree = computed<IntentTreeNode[]>(() => {
  return routes.value.map((route) => {
    const children = intents.value
      .filter((intent) => intent.route === route.name)
      .map((intent) => ({
        key: intentNodeKey(intent.name),
        kind: "intent" as const,
        label: intent.zh,
        caption: intent.name,
        searchText:
          `${intent.name} ${intent.zh} ${intent.description}`.toLowerCase(),
        routeName: route.name,
        intentName: intent.name,
      }));
    return {
      key: routeNodeKey(route.name),
      kind: "route" as const,
      label: route.zh,
      caption: `${route.name} · ${children.length} 个 Intent`,
      searchText:
        `${route.name} ${route.zh} ${route.description}`.toLowerCase(),
      routeName: route.name,
      children,
    };
  });
});

function filterIntentTreeNode(value: string, data: IntentTreeNode) {
  return !value.trim() || data.searchText.includes(value.trim().toLowerCase());
}

watch(intentSearch, (value) => intentTreeRef.value?.filter(value));

watch(selectedIntentName, (name) => {
  void nextTick(() => {
    intentTreeRef.value?.setCurrentKey(name ? intentNodeKey(name) : undefined);
  });
});

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
    intents.value = structuredClone(value.draft_json.intents);
    examples.value = structuredClone(value.draft_json.examples);
    for (const key of Object.keys(editors) as (keyof typeof editors)[])
      editors[key] = pretty(value.draft_json[key]);
    const selected =
      intents.value.find(
        (intent) => intent.name === selectedIntentName.value,
      ) ?? intents.value[0];
    if (selected) selectIntent(selected);
  }
  dirty.value = false;
  summary.value = undefined;
}
function draftPayload(): DraftJson {
  const result: Record<string, unknown> = {
    schema_version: 1,
    routes: routes.value,
    intents: intents.value,
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

function parseExamplesEditor(): Example[] {
  try {
    return JSON.parse(editors.examples) as Example[];
  } catch {
    throw new Error("examples：JSON 格式错误，请检查引号、逗号和括号");
  }
}

function updateExamples(next: Example[]) {
  examples.value = next;
  editors.examples = pretty(next);
}

function applyLocal(action: () => void) {
  error.value = "";
  message.value = "";
  try {
    action();
  } catch (value) {
    error.value = value instanceof Error ? value.message : String(value);
  }
}

function openNewRoute() {
  editingRouteName.value = null;
  Object.assign(routeForm, {
    name: "",
    zh: "",
    description: "",
    enabled: true,
  });
  routeDialogVisible.value = true;
}

function openRoute(route: Route) {
  editingRouteName.value = route.name;
  Object.assign(routeForm, {
    name: route.name,
    zh: route.zh,
    description: route.description,
    enabled: route.enabled,
  });
  routeDialogVisible.value = true;
}

function saveRouteForm() {
  const name = routeForm.name.trim();
  const zh = routeForm.zh.trim();
  const description = routeForm.description.trim();
  if (!name || !zh || !description)
    throw new Error("Route 标识、名称和说明不能为空");
  if (
    routes.value.some(
      (route) => route.name === name && route.name !== editingRouteName.value,
    )
  )
    throw new Error(`Route 标识 ${name} 已存在`);

  const nextExamples = parseExamplesEditor();
  const next: Route = { name, zh, description, enabled: true };
  if (editingRouteName.value === null) routes.value.push(next);
  else {
    const index = routes.value.findIndex(
      (route) => route.name === editingRouteName.value,
    );
    if (index >= 0) routes.value[index] = next;
    if (editingRouteName.value !== name) {
      intents.value.forEach((intent) => {
        if (intent.route === editingRouteName.value) intent.route = name;
      });
      if (intentForm.route === editingRouteName.value) intentForm.route = name;
      nextExamples.forEach((example) => {
        if (example.route === editingRouteName.value) example.route = name;
      });
      updateExamples(nextExamples);
    }
  }
  editingRouteName.value = name;
  dirty.value = true;
}

async function saveRoute() {
  await run(async () => {
    saveRouteForm();
    acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
    routeDialogVisible.value = false;
    message.value = `Route ${routeForm.name.trim()} 已保存`;
  });
}

function routeIntentCount(routeName: string) {
  return intents.value.filter((intent) => intent.route === routeName).length;
}

async function deleteRoute(route: Route) {
  if (routes.value.length <= 1) {
    error.value = "至少需要保留一个 Route，无法删除当前唯一的 Route";
    return;
  }
  const routeIntents = intents.value.filter(
    (intent) => intent.route === route.name,
  );
  const intentLabel = routeIntents.length
    ? `，并级联删除其下 ${routeIntents.length} 个 Intent 及相关典型说法`
    : "";
  try {
    await ElMessageBox.confirm(
      `确定删除 Route ${route.zh}（${route.name}）${intentLabel}？`,
      "删除 Route",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    await run(async () => {
      const removedIntentNames = new Set(
        routeIntents.map((intent) => intent.name),
      );
      routes.value = routes.value.filter((item) => item.name !== route.name);
      intents.value = intents.value.filter(
        (intent) => intent.route !== route.name,
      );
      updateExamples(
        parseExamplesEditor().filter(
          (example) =>
            example.route !== route.name &&
            (!example.intent || !removedIntentNames.has(example.intent)),
        ),
      );
      if (
        selectedIntentName.value &&
        removedIntentNames.has(selectedIntentName.value)
      ) {
        const next = intents.value[0];
        if (next) selectIntent(next);
        else resetIntentEditor();
      }
      dirty.value = true;
      acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
      message.value = `Route ${route.name} 已删除`;
    });
  } catch (value) {
    if (value !== "cancel" && value !== "close")
      error.value = value instanceof Error ? value.message : String(value);
  }
}

function selectIntent(intent: Intent) {
  const currentExamples = parseExamplesEditor();
  examples.value = currentExamples;
  selectedIntentName.value = intent.name;
  isNewIntent.value = false;
  Object.assign(intentForm, intent, {
    aliases: [...(intent.aliases ?? [])],
    utterances: currentExamples
      .filter((example) => example.intent === intent.name)
      .map((example) => example.text),
  });
  utteranceInput.value = "";
}

function newIntent(routeName?: string) {
  selectedIntentName.value = null;
  isNewIntent.value = true;
  const selectedRoute = routes.value.some((route) => route.name === routeName)
    ? routeName
    : routes.value.some((route) => route.name === intentForm.route)
      ? intentForm.route
      : routes.value[0]?.name;
  Object.assign(intentForm, {
    name: "",
    zh: "",
    route: selectedRoute ?? "",
    description: "",
    enabled: true,
    aliases: [],
    mapping_note: null,
    utterances: [],
  });
  utteranceInput.value = "";
}

function resetIntentEditor() {
  selectedIntentName.value = null;
  isNewIntent.value = false;
  Object.assign(intentForm, {
    name: "",
    zh: "",
    route: routes.value[0]?.name ?? "",
    description: "",
    enabled: true,
    aliases: [],
    mapping_note: null,
    utterances: [],
  });
  utteranceInput.value = "";
}

function handleIntentTreeNodeClick(data: IntentTreeNode) {
  if (data.kind !== "intent" || !data.intentName) {
    void nextTick(() => {
      intentTreeRef.value?.setCurrentKey(
        selectedIntentName.value
          ? intentNodeKey(selectedIntentName.value)
          : data.key,
      );
    });
    return;
  }
  const intent = intents.value.find((item) => item.name === data.intentName);
  if (intent) applyLocal(() => selectIntent(intent));
}

function addUtterance() {
  const text = utteranceInput.value.trim();
  if (!text || intentForm.utterances.includes(text)) return;
  intentForm.utterances.push(text);
  utteranceInput.value = "";
}

function removeUtterance(index: number) {
  intentForm.utterances.splice(index, 1);
}

function saveIntentForm() {
  const name = intentForm.name.trim();
  const zh = intentForm.zh.trim();
  const route = intentForm.route.trim();
  const description = intentForm.description.trim();
  if (!name || !zh || !route || !description)
    throw new Error("Intent 标识、名称、所属 Route 和说明不能为空");
  if (!routes.value.some((item) => item.name === route))
    throw new Error(`所属 Route ${route} 不存在`);
  if (
    intents.value.some(
      (intent) =>
        intent.name === name && intent.name !== selectedIntentName.value,
    )
  )
    throw new Error(`Intent 标识 ${name} 已存在`);

  const oldName = selectedIntentName.value;
  const next: Intent = {
    name,
    zh,
    route,
    description,
    enabled: intentForm.enabled,
    aliases: [...(intentForm.aliases ?? [])],
    ...(intentForm.mapping_note
      ? { mapping_note: intentForm.mapping_note }
      : {}),
  };
  if (isNewIntent.value) intents.value.push(next);
  else {
    const index = intents.value.findIndex((intent) => intent.name === oldName);
    if (index >= 0) intents.value[index] = next;
  }

  const retained = parseExamplesEditor().filter(
    (example) => example.intent !== oldName && example.intent !== name,
  );
  const utterances = [
    ...new Set(intentForm.utterances.map((item) => item.trim())),
  ]
    .filter(Boolean)
    .map((text) => ({ text, route, intent: name, enabled: true }));
  updateExamples([...retained, ...utterances]);
  selectedIntentName.value = name;
  isNewIntent.value = false;
  dirty.value = true;
}

async function saveIntent() {
  await run(async () => {
    saveIntentForm();
    acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
    message.value = `Intent ${intentForm.name.trim()} 已保存`;
  });
}

async function deleteIntent(intentName?: string | null) {
  const name = intentName ?? selectedIntentName.value;
  if (!name) return;
  const deletingSelected = selectedIntentName.value === name;
  try {
    await ElMessageBox.confirm(
      `删除 Intent ${name}，并同时删除它的典型说法？`,
      "删除 Intent",
    );
    await run(async () => {
      intents.value = intents.value.filter((intent) => intent.name !== name);
      updateExamples(
        parseExamplesEditor().filter((example) => example.intent !== name),
      );
      dirty.value = true;
      if (deletingSelected) {
        const next = intents.value[0];
        if (next) selectIntent(next);
        else resetIntentEditor();
      }
      acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
      message.value = `Intent ${name} 已删除`;
    });
  } catch (value) {
    if (value !== "cancel" && value !== "close")
      error.value = value instanceof Error ? value.message : String(value);
  }
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
    message.value = "配置已保存";
  });
}
async function validate() {
  await run(async () => {
    await configApi.validate();
    message.value = "校验通过：Route、Intent、名称和引用合法";
  });
}
async function showPreview() {
  await run(async () => {
    const value = await configApi.preview(previewText.value);
    preview.value = value.final_prompt;
    previewTitle.value = "完整 Prompt 预览";
    previewVisible.value = true;
  });
}
async function showModulePreview(
  module: "routes" | "intents" | "intent",
  requestedIntentName?: string,
) {
  await run(async () => {
    const intentName =
      module === "intent"
        ? (requestedIntentName ?? selectedIntentName.value)
        : null;
    if (module === "intent" && !intentName)
      throw new Error("请先选择一个已保存的 Intent");
    const value = await configApi.previewModule(
      module,
      intentName ?? undefined,
    );
    preview.value = value.content;
    previewTitle.value =
      module === "routes"
        ? "Route 提示词预览"
        : module === "intents"
          ? "全部 Intent 提示词预览"
          : `单个 Intent 提示词预览 · ${intentName}`;
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
    <div v-if="!isPromptConfigSection" class="config-heading">
      <div>
        <p>编辑配置 → 校验 → Prompt 预览 → 应用配置</p>
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
    <div
      v-if="draft.draft_json && !isPromptConfigSection"
      class="toolbar"
    >
      <el-button type="primary" @click="save" :disabled="busy || !dirty"
        >保存配置</el-button
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
        dirty ? "未保存" : "配置已同步"
      }}</el-tag>
    </div>
    <div class="config-section">
      <section v-if="section === 'routes'" class="config-editor">
        <div class="section-actions">
          <el-button
            @click="showModulePreview('routes')"
            :disabled="busy || dirty"
          >
            Route 提示词预览
          </el-button>
          <el-button type="primary" @click="openNewRoute">新增 Route</el-button>
        </div>
        <el-table :data="routes" row-key="name" class="route-table">
          <el-table-column prop="name" label="Route 标识" min-width="190" />
          <el-table-column prop="zh" label="名称" min-width="130" />
          <el-table-column prop="description" label="说明" min-width="280" />
          <el-table-column label="Intent 数" width="100">
            <template #default="{ row }">{{
              routeIntentCount(row.name)
            }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button link type="primary" @click="openRoute(row)"
                >编辑</el-button
              >
              <el-button link type="danger" @click="deleteRoute(row)"
                >删除</el-button
              >
            </template>
          </el-table-column>
        </el-table>
      </section>
      <section v-else-if="section === 'intents'" class="config-editor">
        <div class="section-actions">
          <el-button
            @click="showModulePreview('intents')"
            :disabled="busy || dirty"
          >
            全部 Intent 提示词预览
          </el-button>
          <el-button type="primary" @click="newIntent()">新增 Intent</el-button>
        </div>
        <div v-if="draft.draft_json" class="intent-manager">
          <aside class="intent-sidebar">
            <el-input
              v-model="intentSearch"
              clearable
              aria-label="搜索 Intent"
              placeholder="搜索 Route / Intent"
            />
            <el-tree
              ref="intentTreeRef"
              class="intent-tree"
              :data="intentTree"
              node-key="key"
              default-expand-all
              highlight-current
              :expand-on-click-node="false"
              :current-node-key="
                selectedIntentName
                  ? intentNodeKey(selectedIntentName)
                  : undefined
              "
              :filter-node-method="filterIntentTreeNode"
              empty-text="暂无 Route"
              @node-click="handleIntentTreeNodeClick"
            >
              <template #default="{ data }">
                <div
                  class="intent-tree-node"
                  :class="`is-${data.kind}`"
                >
                  <span class="intent-tree-label">
                    <span>{{ data.label }}</span>
                    <small>{{ data.caption }}</small>
                  </span>
                  <span class="intent-tree-actions">
                    <el-button
                      v-if="data.kind === 'route'"
                      link
                      type="primary"
                      size="small"
                      @click.stop="newIntent(data.routeName)"
                    >
                      新增 Intent
                    </el-button>
                    <template v-else>
                      <el-button
                        link
                        type="danger"
                        size="small"
                        @click.stop="deleteIntent(data.intentName)"
                      >
                        删除
                      </el-button>
                    </template>
                  </span>
                </div>
              </template>
            </el-tree>
          </aside>
          <div class="intent-detail">
            <el-empty
              v-if="!isNewIntent && !selectedIntentName"
              description="请选择或新增一个 Intent"
            />
            <template v-else>
              <div class="intent-detail-heading">
                <div>
                  <h3>{{ isNewIntent ? "新增 Intent" : intentForm.zh }}</h3>
                  <small>{{ isNewIntent ? "填写节点信息" : intentForm.name }}</small>
                </div>
                <el-button
                  v-if="!isNewIntent"
                  :disabled="busy || dirty"
                  @click="showModulePreview('intent')"
                >
                  单个 Intent 提示词预览
                </el-button>
              </div>
              <div class="intent-form-grid">
                <label>
                  <span>Intent 标识</span>
                  <el-input
                    v-model="intentForm.name"
                    aria-label="Intent 标识"
                  />
                </label>
                <label>
                  <span>显示名称</span>
                  <el-input
                    v-model="intentForm.zh"
                    aria-label="Intent 显示名称"
                  />
                </label>
                <label class="wide-field">
                  <span>所属 Route</span>
                  <el-select
                    v-model="intentForm.route"
                    aria-label="Intent 所属 Route"
                  >
                    <el-option
                      v-for="route in routes"
                      :key="route.name"
                      :label="`${route.zh} (${route.name})`"
                      :value="route.name"
                    />
                  </el-select>
                </label>
                <label class="wide-field">
                  <span>说明</span>
                  <el-input
                    v-model="intentForm.description"
                    aria-label="Intent 说明"
                    type="textarea"
                    :rows="3"
                  />
                </label>
              </div>
              <div class="utterance-editor">
                <h3>典型用户说法</h3>
                <div class="utterance-add">
                  <el-input
                    v-model="utteranceInput"
                    aria-label="典型用户说法"
                    placeholder="输入一句典型说法"
                    @keyup.enter="addUtterance"
                  />
                  <el-button @click="addUtterance">添加</el-button>
                </div>
                <div class="utterance-list">
                  <div
                    v-for="(utterance, index) in intentForm.utterances"
                    :key="`${utterance}-${index}`"
                    class="utterance-row"
                  >
                    <span>{{ utterance }}</span>
                    <el-button
                      link
                      type="danger"
                      @click="removeUtterance(index)"
                      >删除</el-button
                    >
                  </div>
                  <p v-if="!intentForm.utterances.length" class="empty-group">
                    暂无典型说法
                  </p>
                </div>
              </div>
              <div class="intent-actions">
                <el-button
                  v-if="!isNewIntent"
                  type="danger"
                  plain
                  @click="deleteIntent()"
                  >删除 Intent</el-button
                >
                <el-button type="primary" @click="saveIntent">
                  保存 Intent
                </el-button>
              </div>
            </template>
          </div>
        </div>
      </section>
      <section v-else-if="section === 'slots'" class="config-editor">
        <template v-if="draft.draft_json">
          <p>
            枚举槽位指定 value_type=enum 和已有 enum_group；字符串槽位指定
            value_type=string。
          </p>
          <el-input
            aria-label="Slots JSON"
            v-model="editors.slots"
            type="textarea"
            :rows="22"
            @input="dirty = true"
          />
        </template>
      </section>
      <section v-else-if="section === 'enums'" class="config-editor">
        <template v-if="draft.draft_json">
          <p>
            按枚举组编辑 canonical / display / aliases / enabled；Intent 别名在
            Intent 标签维护。
          </p>
          <el-input
            aria-label="Enums JSON"
            v-model="editors.enums"
            type="textarea"
            :rows="22"
            @input="dirty = true"
          />
        </template>
      </section>
      <section v-else-if="section === 'examples'" class="config-editor">
        <template v-if="draft.draft_json">
          <p>维护用于区分 Route 和 Intent 边界的 Few-shot 示例。</p>
          <label for="examples-editor"
            >Examples JSON（text / route / intent / enabled）</label
          >
          <el-input
            id="examples-editor"
            v-model="editors.examples"
            type="textarea"
            :rows="22"
            @input="dirty = true"
          />
        </template>
      </section>
      <section v-else-if="section === 'prompt'" class="config-editor">
        <template v-if="draft.draft_json">
          <p>编辑 system 和 rules，预览完整 Prompt。</p>
          <el-input
            aria-label="Prompt Template JSON"
            v-model="editors.prompt_template"
            type="textarea"
            :rows="22"
            @input="dirty = true"
          />
        </template>
      </section>
      <section v-else-if="section === 'releases'" class="config-editor">
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
      </section>
    </div>
    <el-dialog
      v-model="routeDialogVisible"
      :title="editingRouteName ? '编辑 Route' : '新增 Route'"
      width="560px"
    >
      <div class="dialog-form">
        <label>
          <span>Route 标识</span>
          <el-input v-model="routeForm.name" aria-label="Route 标识" />
        </label>
        <label>
          <span>名称</span>
          <el-input v-model="routeForm.zh" aria-label="Route 名称" />
        </label>
        <label>
          <span>说明</span>
          <el-input
            v-model="routeForm.description"
            aria-label="Route 说明"
            type="textarea"
            :rows="4"
          />
        </label>
      </div>
      <template #footer>
        <el-button @click="routeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRoute">
          保存 Route
        </el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="previewVisible" :title="previewTitle" width="760px">
      <pre class="prompt-view">{{ preview }}</pre>
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
