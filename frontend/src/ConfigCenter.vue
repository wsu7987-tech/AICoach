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
  type PublishSummary,
  type Release,
  type Route,
  type FieldIssue,
  type SlotDefinition,
  type EnumValueDefinition,
  type PromptModule,
  type PromptTemplate,
} from "./configApi";

const props = defineProps<{ section?: string }>();
const emit = defineEmits<{ navigate: [path: "/config/enums"] }>();

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
const slots = ref<SlotDefinition[]>([]);
const enumGroups = ref<Record<string, EnumValueDefinition[]>>({});
const examples = ref<Example[]>([]);
const promptTemplate = reactive<PromptTemplate>({
  system: "",
  rules: [],
  include_examples: true,
});
const newPromptRule = ref("");
const releases = ref<Release[]>([]);
const releaseOffset = ref(0);
const activeId = ref<number | null>(null);
const activeRelease = ref<Release | null>(null);
const validationPassed = ref(false);
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
const isPromptConfigSection = computed(
  () => props.section === "routes" || props.section === "intents",
);
const isParameterSection = computed(
  () => props.section === "slots" || props.section === "enums",
);
const isPromptTemplateSection = computed(() => props.section === "prompt");
const isReleaseSection = computed(() => props.section === "releases");

const sectionLabels: Record<string, string> = {
  routes: "Route",
  intents: "Intent",
  slots: "Slot",
  enums: "Enum / Alias",
  examples: "典型说法",
  prompt_template: "提示词",
  schema_version: "配置结构",
};

function changeDescription(change: PublishSummary["changes"][number]) {
  const label = sectionLabels[change.section] ?? change.section;
  if (Array.isArray(change.before) && Array.isArray(change.after))
    return `${label}：${change.before.length} 项 → ${change.after.length} 项`;
  if (
    change.before &&
    change.after &&
    typeof change.before === "object" &&
    typeof change.after === "object"
  )
    return `${label}：内容已调整`;
  return `${label}：已修改`;
}

const releaseDetailSections = computed(() => {
  const snapshot = detail.value?.snapshot_json;
  if (!snapshot) return [];
  return [
    { label: "Route", value: `${snapshot.routes.length} 项` },
    { label: "Intent", value: `${snapshot.intents.length} 项` },
    { label: "Slot", value: `${snapshot.slots.length} 项` },
    { label: "Enum / Alias", value: `${Object.keys(snapshot.enums).length} 组` },
    {
      label: "典型说法",
      value: `${snapshot.examples.length} 条${
        snapshot.prompt_template.include_examples === false
          ? "（未注入 Prompt）"
          : ""
      }`,
    },
    {
      label: "提示词规则",
      value: `${snapshot.prompt_template.rules.length} 条`,
    },
  ];
});

function formatLocalTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const promptComposition = computed(() => [
  {
    label: "Route 定义",
    detail: `${routes.value.filter((route) => route.enabled).length} 个已启用 Route`,
  },
  {
    label: "Intent 定义",
    detail: `${intents.value.filter((intent) => intent.enabled).length} 个已启用 Intent`,
    enabled: true,
  },
  {
    label: "典型说法",
    detail: promptTemplate.include_examples
      ? `${examples.value.filter((example) => example.enabled !== false).length} 条已启用样例`
      : "已关闭，不写入最终 Prompt",
    enabled: promptTemplate.include_examples,
  },
  {
    label: "文本型 Slot",
    detail: `${slots.value.filter((slot) => slot.enabled && slot.value_type === "string").length} 个由模型提取`,
    enabled: true,
  },
  {
    label: "输出格式",
    detail: "系统自动生成 JSON Schema 和标准示例",
    enabled: true,
  },
]);

type ExampleRow = { item: Example; index: number };
const exampleSearch = ref("");
const exampleRouteFilter = ref("");
const exampleStatusFilter = ref<"" | "enabled" | "disabled">("");
const exampleDialogVisible = ref(false);
const editingExampleIndex = ref<number | null>(null);
const exampleForm = reactive<Example>({
  text: "",
  route: "",
  intent: null,
  enabled: true,
});

const exampleIntentOptions = computed(() =>
  intents.value.filter((intent) => intent.route === exampleForm.route),
);

const filteredExamples = computed<ExampleRow[]>(() => {
  const query = exampleSearch.value.trim().toLowerCase();
  return examples.value
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      const intent = intents.value.find((value) => value.name === item.intent);
      const route = routes.value.find((value) => value.name === item.route);
      const matchesQuery =
        !query ||
        `${item.text} ${item.route} ${route?.zh ?? ""} ${item.intent ?? ""} ${intent?.zh ?? ""}`
          .toLowerCase()
          .includes(query);
      const matchesRoute =
        !exampleRouteFilter.value || item.route === exampleRouteFilter.value;
      const enabled = item.enabled !== false;
      const matchesStatus =
        !exampleStatusFilter.value ||
        (exampleStatusFilter.value === "enabled" ? enabled : !enabled);
      return matchesQuery && matchesRoute && matchesStatus;
    });
});

const exampleStats = computed(() => ({
  total: examples.value.length,
  enabled: examples.value.filter((example) => example.enabled !== false).length,
  intent: examples.value.filter((example) => example.intent).length,
  routeOnly: examples.value.filter((example) => !example.intent).length,
}));

const routeDialogVisible = ref(false);
const editingRouteName = ref<string | null>(null);
const routeForm = reactive<Route>({
  name: "",
  zh: "",
  description: "",
  enabled: true,
});

const slotSearch = ref("");
const slotTypeFilter = ref<"string" | "enum" | "">("");
const slotDialogVisible = ref(false);
const editingSlotName = ref<string | null>(null);
const slotForm = reactive<SlotDefinition>({
  name: "",
  zh: "",
  description: "",
  value_type: "string",
  enabled: true,
  enum_group: null,
});

const enumGroupSearch = ref("");
const selectedEnumGroup = ref<string | null>(null);
const enumGroupDialogVisible = ref(false);
const editingEnumGroupName = ref<string | null>(null);
const enumGroupNameInput = ref("");
const enumValueDialogVisible = ref(false);
const editingEnumValueIndex = ref<number | null>(null);
const enumAliasInput = ref("");
const enumValueForm = reactive<EnumValueDefinition>({
  canonical: "",
  display: "",
  aliases: [],
  enabled: true,
});

const filteredSlots = computed(() => {
  const query = slotSearch.value.trim().toLowerCase();
  return slots.value.filter((slot) => {
    const matchesQuery =
      !query ||
      `${slot.name} ${slot.zh} ${slot.description}`
        .toLowerCase()
        .includes(query);
    return (
      matchesQuery &&
      (!slotTypeFilter.value || slot.value_type === slotTypeFilter.value)
    );
  });
});

const slotStats = computed(() => ({
  total: slots.value.length,
  enabled: slots.value.filter((slot) => slot.enabled).length,
  strings: slots.value.filter((slot) => slot.value_type === "string").length,
  enums: slots.value.filter((slot) => slot.value_type === "enum").length,
}));

function enumGroupUsage(groupName: string) {
  return slots.value.filter((slot) => slot.enum_group === groupName);
}

function goToEnumGroup(groupName: string | null | undefined) {
  if (!groupName) return;
  selectedEnumGroup.value = groupName;
  emit("navigate", "/config/enums");
}

const filteredEnumGroups = computed(() => {
  const query = enumGroupSearch.value.trim().toLowerCase();
  return Object.entries(enumGroups.value)
    .map(([name, values]) => {
      const usage = enumGroupUsage(name);
      return {
        name,
        valueCount: values.length,
        enabledCount: values.filter((value) => value.enabled !== false).length,
        slotCount: usage.length,
        slotName: usage[0]?.name ?? null,
        slotZh: usage[0]?.zh ?? null,
        valueMode: usage.some((slot) => slot.value_type === "enum")
          ? "程序词典"
          : "LLM 示例",
      };
    })
    .filter((group) => !query || group.name.toLowerCase().includes(query));
});

const selectedEnumValues = computed(() =>
  selectedEnumGroup.value
    ? (enumGroups.value[selectedEnumGroup.value] ?? [])
    : [],
);

const selectedEnumUsage = computed(() =>
  selectedEnumGroup.value ? enumGroupUsage(selectedEnumGroup.value) : [],
);

const selectedEnumSlot = computed(() => selectedEnumUsage.value[0] ?? null);
const selectedGroupIsText = computed(
  () =>
    selectedEnumUsage.value.length > 0 &&
    selectedEnumUsage.value.every((slot) => slot.value_type === "string"),
);

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

watch(
  () => props.section,
  (section) => {
    if (section !== "intents" || !selectedIntentName.value) return;
    const intent = intents.value.find(
      (item) => item.name === selectedIntentName.value,
    );
    if (intent) selectIntent(intent);
  },
);

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
    slots.value = structuredClone(value.draft_json.slots);
    enumGroups.value = Object.fromEntries(
      Object.entries(structuredClone(value.draft_json.enums)).map(
        ([groupName, values]) => [
          groupName,
          values.map((enumValue) => ({
            ...enumValue,
            aliases: [...(enumValue.aliases ?? [])],
            enabled: enumValue.enabled !== false,
          })),
        ],
      ),
    );
    for (const slot of slots.value) {
      const parentName = slot.enum_group?.trim() || slot.name;
      slot.enum_group = parentName;
      if (!Object.prototype.hasOwnProperty.call(enumGroups.value, parentName))
        enumGroups.value[parentName] = [];
    }
    examples.value = structuredClone(value.draft_json.examples).map((example) => ({
      ...example,
      intent: example.intent ?? null,
      enabled: example.enabled !== false,
    }));
    promptTemplate.system = value.draft_json.prompt_template.system;
    promptTemplate.include_examples =
      value.draft_json.prompt_template.include_examples ?? true;
    promptTemplate.rules.splice(
      0,
      promptTemplate.rules.length,
      ...value.draft_json.prompt_template.rules,
    );
    newPromptRule.value = "";
    if (
      !selectedEnumGroup.value ||
      !Object.prototype.hasOwnProperty.call(
        enumGroups.value,
        selectedEnumGroup.value,
      )
    ) {
      selectedEnumGroup.value = Object.keys(enumGroups.value)[0] ?? null;
    }
    const selected =
      intents.value.find(
        (intent) => intent.name === selectedIntentName.value,
      ) ?? intents.value[0];
    if (selected) selectIntent(selected);
  }
  dirty.value = false;
  validationPassed.value = false;
  summary.value = undefined;
}
function draftPayload(): DraftJson {
  const result: Record<string, unknown> = {
    schema_version: 1,
    routes: routes.value,
    intents: intents.value,
    slots: slots.value,
    enums: enumGroups.value,
    examples: examples.value,
    prompt_template: normalizedPromptTemplate(),
  };
  return result as unknown as DraftJson;
}

function normalizedPromptTemplate(): PromptTemplate {
  const system = promptTemplate.system;
  const rules = [...promptTemplate.rules];
  if (!system.trim()) throw new Error("System Prompt 不能为空");
  if (rules.some((rule) => !rule.trim())) throw new Error("识别规则不能为空");
  const normalizedRules = rules.map((rule) => rule.trim());
  const duplicate = normalizedRules.find(
    (rule, index) => normalizedRules.indexOf(rule) !== index,
  );
  if (duplicate) throw new Error(`识别规则重复：${duplicate}`);
  return {
    system,
    rules,
    include_examples: promptTemplate.include_examples,
  };
}

function addPromptRule() {
  applyLocal(() => {
    const rule = newPromptRule.value.trim();
    if (!rule) throw new Error("请输入规则内容");
    if (promptTemplate.rules.some((item) => item.trim() === rule))
      throw new Error("这条规则已经存在");
    promptTemplate.rules.push(rule);
    newPromptRule.value = "";
    markDirty();
  });
}

function removePromptRule(index: number) {
  promptTemplate.rules.splice(index, 1);
  markDirty();
}

function movePromptRule(index: number, offset: -1 | 1) {
  const target = index + offset;
  if (target < 0 || target >= promptTemplate.rules.length) return;
  const [rule] = promptTemplate.rules.splice(index, 1);
  promptTemplate.rules.splice(target, 0, rule);
  markDirty();
}

function markDirty() {
  dirty.value = true;
  message.value = "";
}

function openNewSlot() {
  error.value = "";
  editingSlotName.value = null;
  Object.assign(slotForm, {
    name: "",
    zh: "",
    description: "",
    value_type: "string",
    enabled: true,
    enum_group: null,
  });
  slotDialogVisible.value = true;
}

function openSlot(slot: SlotDefinition) {
  error.value = "";
  editingSlotName.value = slot.name;
  Object.assign(slotForm, {
    name: slot.name,
    zh: slot.zh,
    description: slot.description,
    value_type: slot.value_type,
    enabled: slot.enabled,
    enum_group: slot.enum_group ?? null,
  });
  slotDialogVisible.value = true;
}

function editSlot(slot: SlotDefinition) {
  applyLocal(() => openSlot(slot));
}

function applySlotForm() {
  applyLocal(() => {
    const name = slotForm.name.trim();
    const zh = slotForm.zh.trim();
    const description = slotForm.description.trim();
    const current = slots.value.find(
      (slot) => slot.name === editingSlotName.value,
    );
    const currentParent = current?.enum_group;
    let enumGroup = slotForm.enum_group?.trim() || name;
    if (!name || !zh || !description)
      throw new Error("Slot 标识、显示名称和说明不能为空");
    if (
      slots.value.some(
        (slot) => slot.name === name && slot.name !== editingSlotName.value,
      )
    )
      throw new Error(`Slot 标识 ${name} 已存在`);
    if (
      current &&
      current.name !== name &&
      currentParent === current.name &&
      enumGroup === currentParent &&
      enumGroupUsage(currentParent).length === 1
    ) {
      const values = enumGroups.value[currentParent] ?? [];
      const renamed = { ...enumGroups.value };
      delete renamed[currentParent];
      renamed[name] = values;
      enumGroups.value = renamed;
      if (selectedEnumGroup.value === currentParent)
        selectedEnumGroup.value = name;
      enumGroup = name;
    }
    if (!Object.prototype.hasOwnProperty.call(enumGroups.value, enumGroup))
      enumGroups.value[enumGroup] = [];

    const next: SlotDefinition = {
      name,
      zh,
      description,
      value_type: slotForm.value_type,
      enabled: slotForm.enabled,
      enum_group: enumGroup,
    };
    if (editingSlotName.value === null) slots.value.push(next);
    else {
      const index = slots.value.findIndex(
        (slot) => slot.name === editingSlotName.value,
      );
      if (index >= 0) slots.value[index] = next;
    }
    editingSlotName.value = name;
    slotDialogVisible.value = false;
    markDirty();
  });
}

async function deleteSlot(slot: SlotDefinition) {
  try {
    await ElMessageBox.confirm(
      `确定删除 Slot ${slot.zh}（${slot.name}）？发布后模型将不再提取这个参数。`,
      "删除 Slot",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    const parentName = slot.enum_group;
    slots.value = slots.value.filter((item) => item.name !== slot.name);
    if (parentName && enumGroupUsage(parentName).length === 0) {
      const next = { ...enumGroups.value };
      delete next[parentName];
      enumGroups.value = next;
      if (selectedEnumGroup.value === parentName)
        selectedEnumGroup.value = Object.keys(next)[0] ?? null;
    }
    markDirty();
  } catch (value) {
    if (value !== "cancel" && value !== "close")
      error.value = value instanceof Error ? value.message : String(value);
  }
}

function openNewEnumGroup() {
  error.value = "";
  editingEnumGroupName.value = null;
  enumGroupNameInput.value = "";
  enumGroupDialogVisible.value = true;
}

function openRenameEnumGroup() {
  if (!selectedEnumGroup.value) return;
  error.value = "";
  editingEnumGroupName.value = selectedEnumGroup.value;
  enumGroupNameInput.value = selectedEnumGroup.value;
  enumGroupDialogVisible.value = true;
}

function applyEnumGroupForm() {
  applyLocal(() => {
    const name = enumGroupNameInput.value.trim();
    if (!name) throw new Error("Enum Group 标识不能为空");
    if (
      Object.prototype.hasOwnProperty.call(enumGroups.value, name) &&
      name !== editingEnumGroupName.value
    )
      throw new Error(`Enum Group ${name} 已存在`);

    if (editingEnumGroupName.value === null) {
      enumGroups.value[name] = [];
    } else if (editingEnumGroupName.value !== name) {
      const renamed: Record<string, EnumValueDefinition[]> = {};
      for (const [groupName, values] of Object.entries(enumGroups.value))
        renamed[groupName === editingEnumGroupName.value ? name : groupName] =
          values;
      enumGroups.value = renamed;
      slots.value.forEach((slot) => {
        if (slot.enum_group === editingEnumGroupName.value)
          slot.enum_group = name;
      });
    }
    selectedEnumGroup.value = name;
    enumGroupDialogVisible.value = false;
    markDirty();
  });
}

async function deleteSelectedEnumGroup() {
  const name = selectedEnumGroup.value;
  if (!name) return;
  const usage = enumGroupUsage(name);
  if (usage.length) {
    error.value = `Enum Group ${name} 正被 Slot ${usage
      .map((slot) => slot.name)
      .join("、")} 使用，请先改绑这些 Slot`;
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确定删除 Enum Group ${name} 及其全部枚举值？`,
      "删除 Enum Group",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    const next = { ...enumGroups.value };
    delete next[name];
    enumGroups.value = next;
    selectedEnumGroup.value = Object.keys(next)[0] ?? null;
    markDirty();
  } catch (value) {
    if (value !== "cancel" && value !== "close")
      error.value = value instanceof Error ? value.message : String(value);
  }
}

function selectEnumGroup(name: string) {
  selectedEnumGroup.value = name;
  error.value = "";
  message.value = "";
}

function openNewEnumValue() {
  if (!selectedEnumGroup.value) return;
  error.value = "";
  editingEnumValueIndex.value = null;
  enumAliasInput.value = "";
  Object.assign(enumValueForm, {
    canonical: "",
    display: "",
    aliases: [],
    enabled: true,
  });
  enumValueDialogVisible.value = true;
}

function openEnumValue(value: EnumValueDefinition, index: number) {
  error.value = "";
  editingEnumValueIndex.value = index;
  enumAliasInput.value = "";
  Object.assign(enumValueForm, {
    canonical: value.canonical,
    display: value.display,
    aliases: [...(value.aliases ?? [])],
    enabled: value.enabled !== false,
  });
  enumValueDialogVisible.value = true;
}

function addEnumAlias() {
  const candidates = enumAliasInput.value
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  for (const alias of candidates) {
    if (!enumValueForm.aliases.includes(alias))
      enumValueForm.aliases.push(alias);
  }
  enumAliasInput.value = "";
}

function removeEnumAlias(index: number) {
  enumValueForm.aliases.splice(index, 1);
}

function applyEnumValueForm() {
  applyLocal(() => {
    const groupName = selectedEnumGroup.value;
    if (!groupName) throw new Error("请先选择一个 Enum Group");
    const display = enumValueForm.display.trim();
    const canonical = selectedGroupIsText.value
      ? display
      : enumValueForm.canonical.trim();
    if (!canonical || !display)
      throw new Error("标准值 canonical 和显示名称不能为空");

    const aliases = [
      ...new Set(
        enumValueForm.aliases
          .map((item) => item.trim())
          .filter(
            (item) => item && item !== canonical && item !== display,
          ),
      ),
    ];
    const currentForms = new Set([canonical, display, ...aliases]);
    const values = enumGroups.value[groupName] ?? [];
    for (const [index, value] of values.entries()) {
      if (index === editingEnumValueIndex.value) continue;
      for (const form of [value.canonical, value.display, ...(value.aliases ?? [])]) {
        if (currentForms.has(form))
          throw new Error(
            `“${form}”已属于标准值 ${value.canonical}，同一 Group 内不能重复`,
          );
      }
    }

    const next: EnumValueDefinition = {
      canonical,
      display,
      aliases,
      enabled: enumValueForm.enabled !== false,
    };
    if (editingEnumValueIndex.value === null) values.push(next);
    else values[editingEnumValueIndex.value] = next;
    enumValueDialogVisible.value = false;
    markDirty();
  });
}

async function deleteEnumValue(value: EnumValueDefinition, index: number) {
  try {
    await ElMessageBox.confirm(
      `确定删除枚举值 ${value.display}（${value.canonical}）？`,
      "删除枚举值",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    selectedEnumValues.value.splice(index, 1);
    markDirty();
  } catch (reason) {
    if (reason !== "cancel" && reason !== "close")
      error.value = reason instanceof Error ? reason.message : String(reason);
  }
}

function updateExamples(next: Example[]) {
  examples.value = next;
}

function exampleRouteLabel(routeName: string) {
  const route = routes.value.find((item) => item.name === routeName);
  return route ? `${route.zh}（${route.name}）` : routeName;
}

function exampleIntentLabel(intentName: string | null | undefined) {
  if (!intentName) return "仅用于 Route 判断";
  const intent = intents.value.find((item) => item.name === intentName);
  return intent ? `${intent.zh}（${intent.name}）` : intentName;
}

function openNewExample() {
  editingExampleIndex.value = null;
  Object.assign(exampleForm, {
    text: "",
    route: exampleRouteFilter.value || routes.value[0]?.name || "",
    intent: null,
    enabled: true,
  });
  exampleDialogVisible.value = true;
}

function openExample(row: ExampleRow) {
  editingExampleIndex.value = row.index;
  Object.assign(exampleForm, {
    text: row.item.text,
    route: row.item.route,
    intent: row.item.intent ?? null,
    enabled: row.item.enabled !== false,
  });
  exampleDialogVisible.value = true;
}

function changeExampleRoute() {
  if (
    exampleForm.intent &&
    !intents.value.some(
      (intent) =>
        intent.name === exampleForm.intent && intent.route === exampleForm.route,
    )
  )
    exampleForm.intent = null;
}

function applyExampleForm() {
  applyLocal(() => {
    const text = exampleForm.text.trim();
    const route = exampleForm.route;
    const intent = exampleForm.intent || null;
    if (!text || !route) throw new Error("用户说法和期望 Route 不能为空");
    if (!routes.value.some((item) => item.name === route))
      throw new Error(`Route ${route} 不存在`);
    if (
      intent &&
      !intents.value.some(
        (item) => item.name === intent && item.route === route,
      )
    )
      throw new Error("期望 Intent 必须属于当前选择的 Route");
    if (
      examples.value.some(
        (item, index) =>
          index !== editingExampleIndex.value && item.text.trim() === text,
      )
    )
      throw new Error(`典型说法“${text}”已存在，不能配置多个期望结果`);

    const next: Example = {
      text,
      route,
      intent,
      enabled: exampleForm.enabled !== false,
    };
    if (editingExampleIndex.value === null) examples.value.push(next);
    else examples.value[editingExampleIndex.value] = next;
    exampleDialogVisible.value = false;
    markDirty();
  });
}

async function deleteExample(row: ExampleRow) {
  try {
    await ElMessageBox.confirm(
      `确定删除典型说法“${row.item.text}”？`,
      "删除典型说法",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    examples.value.splice(row.index, 1);
    markDirty();
  } catch (reason) {
    if (reason !== "cancel" && reason !== "close")
      error.value = reason instanceof Error ? reason.message : String(reason);
  }
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

  const nextExamples = examples.value;
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
        examples.value.filter(
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
  const currentExamples = examples.value;
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
  const existingIntentExamples = examples.value.filter(
    (example) => example.intent === oldName || example.intent === name,
  );
  const retained = examples.value.filter(
    (example) => example.intent !== oldName && example.intent !== name,
  );
  const utteranceTexts = [
    ...new Set(intentForm.utterances.map((item) => item.trim())),
  ].filter(Boolean);
  const conflict = utteranceTexts.find((text) =>
    retained.some((example) => example.text.trim() === text),
  );
  if (conflict)
    throw new Error(`典型说法“${conflict}”已用于其他 Route 或 Intent`);
  const utterances = utteranceTexts.map((text) => ({
    text,
    route,
    intent: name,
    enabled:
      existingIntentExamples.find((example) => example.text.trim() === text)
        ?.enabled !== false,
  }));

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
        examples.value.filter((example) => example.intent !== name),
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
async function loadHistory() {
  const history = await configApi.releases(releaseOffset.value);
  releases.value = history.items;
  activeId.value = history.active_release_id;
  if (history.active_release_id === null) {
    activeRelease.value = null;
  } else {
    const activeInPage = history.items.find(
      (release) => release.id === history.active_release_id,
    );
    if (activeInPage) activeRelease.value = activeInPage;
    else if (activeRelease.value?.id !== history.active_release_id)
      activeRelease.value = await configApi.release(history.active_release_id);
  }
}
async function reload() {
  await run(async () => {
    if (dirty.value)
      await ElMessageBox.confirm(
        "重新载入会丢弃本地未保存编辑，是否继续？",
        "重新载入",
      );
    const value = await configApi.draft();
    await loadHistory();
    acceptDraft(value);
    loaded.value = true;
  });
}
async function save() {
  await run(async () => {
    acceptDraft(await configApi.save(draftPayload(), draft.value.draft_hash));
    message.value = isParameterSection.value || isPromptTemplateSection.value
      ? "配置草稿已保存，发布前不会影响线上识别"
      : "配置已保存";
  });
}
async function validate() {
  await run(async () => {
    await configApi.validate();
    validationPassed.value = true;
    message.value = "校验通过：配置结构、名称和引用合法";
  });
}
async function showPreview() {
  if (dirty.value) {
    error.value = "请先保存到配置草稿，再生成最终 Prompt 预览";
    return;
  }
  if (!previewText.value.trim()) {
    error.value = "请输入用于生成 Prompt 的测试文本";
    return;
  }
  await run(async () => {
    const value = await configApi.preview(previewText.value);
    preview.value = value.final_prompt;
    previewTitle.value = "完整 Prompt 预览";
    previewVisible.value = true;
  });
}
async function showModulePreview(
  module: PromptModule,
  requestedTargetName?: string,
) {
  await run(async () => {
    const targetName =
      module === "intent"
        ? (requestedTargetName ?? selectedIntentName.value)
        : module === "enum"
          ? (requestedTargetName ?? selectedEnumGroup.value)
          : requestedTargetName;
    if (module === "intent" && !targetName)
      throw new Error("请先选择一个已保存的 Intent");
    if (module === "slot" && !targetName)
      throw new Error("请先选择一个已保存的 Slot");
    if (module === "enum" && !targetName)
      throw new Error("请先选择一个已保存的 Enum Group");
    const value = await configApi.previewModule(module, targetName ?? undefined);
    preview.value = value.content;
    const targetSlot = targetName
      ? slots.value.find((slot) => slot.name === targetName)
      : undefined;
    const titles: Record<PromptModule, string> = {
      routes: "Route 提示词预览",
      intents: "全部 Intent 提示词预览",
      intent: `单个 Intent 提示词预览 · ${targetName}`,
      slots: "文本 Slot 提示词预览",
      slot:
        targetSlot?.value_type === "enum"
          ? `程序匹配规则预览 · ${targetName}`
          : `文本 Slot 提示词预览 · ${targetName}`,
      enum: selectedGroupIsText.value
        ? `文本 Slot 提示词预览 · ${targetName}`
        : `程序匹配规则预览 · ${targetName}`,
    };
    previewTitle.value = titles[module];
    previewVisible.value = true;
  });
}
async function importBootstrap() {
  await run(async () => {
    acceptDraft(await configApi.bootstrap(bootstrap as DraftJson));
    message.value = "Bootstrap 已导入配置草稿，请确认业务配置后发布";
  });
}
async function preparePublish() {
  await run(async () => {
    summary.value = await configApi.summary();
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
    validationPassed.value = false;
    message.value = `${result.version} 已发布并生效`;
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
      `使用 ${row.version} 的历史配置替换当前配置草稿？${dirty.value ? "本地未保存编辑会丢弃。" : ""}随后需重新发布才能生效。`,
      "基于历史版本恢复",
    );
    acceptDraft(await configApi.restore(row.id, draft.value.draft_hash));
    message.value = `已基于 ${row.version} 创建配置草稿，请校验、预览并重新发布`;
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
    <div v-if="!isPromptConfigSection && !isReleaseSection" class="config-heading">
      <div>
        <p v-if="isParameterSection">
          页面编辑 → 保存到配置草稿 → 校验与预览 → 发布后线上生效
        </p>
        <p v-else-if="isPromptTemplateSection">
          编辑任务说明与全局规则 → 保存到配置草稿 → 预览 → 发布后线上生效
        </p>
        <p v-else>编辑配置 → 校验 → Prompt 预览 → 应用配置</p>
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
      :title="
        isParameterSection || isPromptTemplateSection
          ? '有页面修改尚未保存到配置草稿；当前修改不会影响线上识别。'
          : '有未保存修改，请先保存，再执行校验、预览或发布。'
      "
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
      v-if="draft.draft_json && !isPromptConfigSection && !isReleaseSection"
      class="toolbar"
    >
      <el-button type="primary" @click="save" :disabled="busy || !dirty"
        >{{
          isParameterSection || isPromptTemplateSection
            ? "保存到配置草稿"
            : "保存配置"
        }}</el-button
      >
      <el-button @click="validate" :disabled="busy || dirty">校验</el-button>
      <template v-if="!isPromptTemplateSection">
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
      </template>
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
          <div class="config-page-intro">
            <div>
              <span class="section-kicker">参数提取规则</span>
              <h2>定义参数，并明确由 LLM 或程序负责提取</h2>
              <p>
                文本型 Slot 的说明和少量参考示例进入 Prompt，由 LLM 提取开放文本；
                枚举型 Slot 由程序按标准值、显示名称和别名匹配，完整词典不进入 Prompt。
                保存到配置草稿后，仍需发布才会影响线上识别。
              </p>
            </div>
            <div class="intro-actions">
              <el-button
                @click="showModulePreview('slots')"
                :disabled="busy || dirty"
              >
                文本 Slot 提示词预览
              </el-button>
              <el-button type="primary" @click="openNewSlot">新增 Slot</el-button>
            </div>
          </div>

          <div class="slot-type-guide">
            <article>
              <el-tag type="info" effect="plain">LLM 提取 · string</el-tag>
              <strong>让 LLM 从原话中提取开放文本</strong>
              <p>
                Slot 名称、说明和参考示例会进入 Prompt；参考示例不构成候选集合。
                适合时长、动作名等无法穷举的内容。
              </p>
            </article>
            <article>
              <el-tag type="primary" effect="plain">程序提取 · enum</el-tag>
              <strong>由程序把有限说法映射为标准值</strong>
              <p>
                canonical、display 和 aliases 构成匹配词典，完整词典不进入 Prompt。
                适合身体部位、状态和等级等可穷举参数。
              </p>
            </article>
          </div>

          <div class="metric-grid" aria-label="Slot 配置概览">
            <div class="metric-card">
              <strong>{{ slotStats.total }}</strong><span>全部 Slot</span>
            </div>
            <div class="metric-card">
              <strong>{{ slotStats.enabled }}</strong><span>已启用</span>
            </div>
            <div class="metric-card">
              <strong>{{ slotStats.strings }}</strong><span>LLM 文本提取</span>
            </div>
            <div class="metric-card">
              <strong>{{ slotStats.enums }}</strong><span>程序枚举提取</span>
            </div>
          </div>

          <div class="manager-toolbar">
            <el-input
              v-model="slotSearch"
              aria-label="搜索 Slot"
              placeholder="搜索标识、名称或说明"
              clearable
            />
            <el-select
              v-model="slotTypeFilter"
              aria-label="筛选 Slot 类型"
              placeholder="全部类型"
              clearable
            >
              <el-option label="LLM 文本提取" value="string" />
              <el-option label="程序枚举提取" value="enum" />
            </el-select>
            <span class="result-count">显示 {{ filteredSlots.length }} 条</span>
          </div>

          <el-table :data="filteredSlots" row-key="name" class="entity-table">
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  :aria-label="`启用 Slot ${row.name}`"
                  @change="markDirty"
                />
              </template>
            </el-table-column>
            <el-table-column label="Slot" min-width="190">
              <template #default="{ row }">
                <div class="entity-name">
                  <strong>{{ row.zh }}</strong>
                  <code>{{ row.name }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="提取内容" min-width="250" />
            <el-table-column label="提取方式" width="150">
              <template #default="{ row }">
                <el-tag :type="row.value_type === 'enum' ? 'primary' : 'info'">
                  {{ row.value_type === "enum" ? "程序 · 枚举" : "LLM · 文本" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="词组父级" min-width="180">
              <template #default="{ row }">
                <template v-if="row.enum_group">
                  <button
                    type="button"
                    class="inline-link"
                    @click="goToEnumGroup(row.enum_group)"
                  >
                    {{ row.enum_group }}
                  </button>
                  <small>
                    {{ enumGroups[row.enum_group]?.length ?? 0 }} 个值
                  </small>
                </template>
                <span v-else class="muted-value">—</span>
              </template>
            </el-table-column>
            <el-table-column
              label="操作"
              width="230"
              align="right"
              fixed="right"
            >
              <template #default="{ row }">
                <el-button
                  size="small"
                  @click="showModulePreview('slot', row.name)"
                  :disabled="busy || dirty || !row.enabled"
                >
                  预览
                </el-button>
                <el-button size="small" type="primary" plain @click="editSlot(row)">
                  编辑
                </el-button>
                <el-button size="small" type="danger" plain @click="deleteSlot(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="没有符合条件的 Slot" :image-size="72" />
            </template>
          </el-table>
        </template>
      </section>
      <section v-else-if="section === 'enums'" class="config-editor">
        <template v-if="draft.draft_json">
          <div class="config-page-intro">
            <div>
              <span class="section-kicker">标准值与同义表达</span>
              <h2>按 Slot 维护 LLM 示例或程序匹配词典</h2>
              <p>
                文本型 Slot 的参考词组可作为少量示例进入 Prompt，不限制模型输出；
                枚举型 Slot 的 canonical、display 和 aliases 由程序直接匹配，不发送完整词典给 LLM。
              </p>
            </div>
          </div>

          <div class="enum-manager">
            <aside class="enum-group-sidebar">
              <el-input
                v-model="enumGroupSearch"
                aria-label="搜索 Enum Group"
                placeholder="搜索 Slot 或词组父级"
                clearable
              />
              <div class="enum-group-list">
                <button
                  v-for="group in filteredEnumGroups"
                  :key="group.name"
                  type="button"
                  class="enum-group-item"
                  :class="{ active: selectedEnumGroup === group.name }"
                  @click="selectEnumGroup(group.name)"
                >
                  <span>
                    <strong>{{ group.slotZh || group.name }}</strong>
                    <small>
                      {{ group.slotName || group.name }} ·
                      {{ group.enabledCount }}/{{ group.valueCount }} 项启用
                    </small>
                  </span>
                  <el-tag
                    size="small"
                    effect="plain"
                    :type="group.valueMode === '程序词典' ? 'primary' : 'info'"
                  >
                    {{ group.valueMode }}
                  </el-tag>
                </button>
                <el-empty
                  v-if="!filteredEnumGroups.length"
                  description="暂无 Enum Group"
                  :image-size="64"
                />
              </div>
            </aside>

            <div class="enum-detail">
              <template v-if="selectedEnumGroup">
                <div class="enum-detail-heading">
                  <div>
                    <span class="section-kicker">Slot 词组父级</span>
                    <h3>
                      {{ selectedEnumSlot?.zh || selectedEnumGroup }}
                      <small v-if="selectedEnumSlot">{{ selectedEnumSlot.name }}</small>
                    </h3>
                    <p v-if="selectedEnumUsage.length" class="usage-line">
                      被
                      <el-tag
                        v-for="slot in selectedEnumUsage"
                        :key="slot.name"
                        size="small"
                        effect="plain"
                      >
                        {{ slot.zh }} · {{ slot.name }}
                      </el-tag>
                      使用
                    </p>
                    <p v-else class="usage-line">当前没有 Slot 使用这个 Group</p>
                  </div>
                  <div class="detail-actions">
                    <el-button
                      @click="showModulePreview('enum')"
                      :disabled="busy || dirty"
                    >
                      {{ selectedGroupIsText ? "提示词预览" : "匹配规则预览" }}
                    </el-button>
                    <el-button
                      v-if="!selectedEnumUsage.length"
                      @click="openRenameEnumGroup"
                    >
                      重命名
                    </el-button>
                    <el-button
                      v-if="!selectedEnumUsage.length"
                      type="danger"
                      plain
                      @click="deleteSelectedEnumGroup"
                    >
                      删除父级
                    </el-button>
                    <el-button type="primary" @click="openNewEnumValue">
                      {{ selectedGroupIsText ? "新增参考示例" : "新增匹配值" }}
                    </el-button>
                  </div>
                </div>

                <el-alert
                  v-if="!selectedEnumValues.some((value) => value.enabled !== false)"
                  :title="
                    selectedGroupIsText
                      ? '该文本型 Slot 还没有参考示例；模型仍可提取任意符合说明的文本。'
                      : '该枚举型 Slot 没有已启用的匹配值，程序无法提取标准值。'
                  "
                  type="warning"
                  :closable="false"
                  show-icon
                />

                <el-table
                  :data="selectedEnumValues"
                  row-key="canonical"
                  class="entity-table enum-value-table"
                >
                  <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                      <el-switch
                        v-model="row.enabled"
                        :active-value="true"
                        :inactive-value="false"
                        :aria-label="`启用枚举值 ${row.canonical}`"
                        @change="markDirty"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column
                    v-if="!selectedGroupIsText"
                    label="标准值 canonical"
                    min-width="170"
                  >
                    <template #default="{ row }"><code>{{ row.canonical }}</code></template>
                  </el-table-column>
                  <el-table-column
                    prop="display"
                    :label="selectedGroupIsText ? '参考示例' : '显示名称'"
                    min-width="140"
                  />
                  <el-table-column
                    :label="selectedGroupIsText ? '相近示例' : '程序可识别说法 aliases'"
                    min-width="260"
                  >
                    <template #default="{ row }">
                      <div v-if="row.aliases?.length" class="tag-list">
                        <el-tag
                          v-for="alias in row.aliases"
                          :key="alias"
                          size="small"
                          type="info"
                        >
                          {{ alias }}
                        </el-tag>
                      </div>
                      <span v-else class="muted-value">暂无别名</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="140" align="right">
                    <template #default="{ row, $index }">
                      <el-button link type="primary" @click="openEnumValue(row, $index)">
                        编辑
                      </el-button>
                      <el-button link type="danger" @click="deleteEnumValue(row, $index)">
                        删除
                      </el-button>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <el-empty
                      :description="
                        selectedGroupIsText
                          ? '这个文本型 Slot 还没有参考示例'
                          : '这个枚举型 Slot 还没有程序匹配值'
                      "
                      :image-size="72"
                    >
                      <el-button type="primary" @click="openNewEnumValue">
                        {{ selectedGroupIsText ? "新增第一个参考示例" : "新增第一个匹配值" }}
                      </el-button>
                    </el-empty>
                  </template>
                </el-table>
              </template>
              <el-empty v-else description="新建或选择一个 Enum Group" />
            </div>
          </div>
        </template>
      </section>
      <section v-else-if="section === 'examples'" class="config-editor">
        <template v-if="draft.draft_json">
          <div class="config-page-intro">
            <div>
              <span class="section-kicker">典型说法库</span>
              <h2>用真实表达补充 Route 和 Intent 的判断边界</h2>
              <p>
                每条说法对应一个期望 Route，可选更具体的 Intent。这里只维护样例；是否把样例写入最终 Prompt，由提示词管理统一控制。
              </p>
            </div>
            <el-button type="primary" @click="openNewExample">新增典型说法</el-button>
          </div>

          <div class="metric-grid" aria-label="典型说法概览">
            <div class="metric-card">
              <strong>{{ exampleStats.total }}</strong><span>全部说法</span>
            </div>
            <div class="metric-card">
              <strong>{{ exampleStats.enabled }}</strong><span>已启用</span>
            </div>
            <div class="metric-card">
              <strong>{{ exampleStats.intent }}</strong><span>Intent 样例</span>
            </div>
            <div class="metric-card">
              <strong>{{ exampleStats.routeOnly }}</strong><span>仅 Route 样例</span>
            </div>
          </div>

          <el-alert
            :type="promptTemplate.include_examples ? 'success' : 'warning'"
            :closable="false"
            show-icon
            class="example-prompt-state"
          >
            <template #title>
              {{
                promptTemplate.include_examples
                  ? "已启用：发布后，启用状态的典型说法会进入最终 Prompt"
                  : "已关闭：典型说法会继续保存，但不会进入最终 Prompt"
              }}
            </template>
          </el-alert>

          <div class="example-toolbar">
            <el-input
              v-model="exampleSearch"
              clearable
              placeholder="搜索用户说法、Route 或 Intent"
              aria-label="搜索典型说法"
            />
            <el-select v-model="exampleRouteFilter" clearable placeholder="全部 Route">
              <el-option
                v-for="route in routes"
                :key="route.name"
                :label="`${route.zh}（${route.name}）`"
                :value="route.name"
              />
            </el-select>
            <el-select v-model="exampleStatusFilter" placeholder="全部状态">
              <el-option label="全部状态" value="" />
              <el-option label="已启用" value="enabled" />
              <el-option label="已停用" value="disabled" />
            </el-select>
          </div>

          <el-table :data="filteredExamples" row-key="index" class="example-table">
            <el-table-column label="用户说法" min-width="260">
              <template #default="{ row }">
                <span class="example-text">{{ row.item.text }}</span>
              </template>
            </el-table-column>
            <el-table-column label="期望 Route" min-width="210">
              <template #default="{ row }">
                {{ exampleRouteLabel(row.item.route) }}
              </template>
            </el-table-column>
            <el-table-column label="期望 Intent" min-width="220">
              <template #default="{ row }">
                <span :class="{ 'muted-value': !row.item.intent }">
                  {{ exampleIntentLabel(row.item.intent) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-switch
                  v-model="row.item.enabled"
                  inline-prompt
                  active-text="启"
                  inactive-text="停"
                  @change="markDirty"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" align="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openExample(row)">编辑</el-button>
                <el-button link type="danger" @click="deleteExample(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="没有符合条件的典型说法" :image-size="72">
                <el-button type="primary" @click="openNewExample">新增第一条说法</el-button>
              </el-empty>
            </template>
          </el-table>
        </template>
      </section>
      <section v-else-if="section === 'prompt'" class="config-editor">
        <template v-if="draft.draft_json">
          <div class="config-page-intro">
            <div>
              <span class="section-kicker">全局识别策略</span>
              <h2>管理模型的任务说明和通用判断规则</h2>
              <p>
                这里只编辑所有请求共用的指令。Route、Intent、文本 Slot、可选典型说法和输出格式会由系统按配置自动拼装，无需复制到这里。
              </p>
            </div>
          </div>

          <div class="prompt-editor-layout">
            <div class="prompt-editor-main">
              <article class="prompt-config-card">
                <header class="prompt-card-heading">
                  <div>
                    <span class="prompt-step">01</span>
                    <div>
                      <h3>System Prompt</h3>
                      <p>定义模型身份、任务边界和不可执行的行为。</p>
                    </div>
                  </div>
                  <span class="field-counter"
                    >{{ promptTemplate.system.length }} 字</span
                  >
                </header>
                <el-input
                  v-model="promptTemplate.system"
                  aria-label="System Prompt"
                  type="textarea"
                  :rows="8"
                  placeholder="说明模型是谁、需要完成什么任务，以及不应执行什么操作"
                  @input="markDirty"
                />
                <p class="field-guidance">
                  建议只放长期稳定的总体要求；具体分类名称、业务说明和输出字段由系统维护。
                </p>
              </article>

              <article class="prompt-config-card">
                <header class="prompt-card-heading">
                  <div>
                    <span class="prompt-step">02</span>
                    <div>
                      <h3>识别规则</h3>
                      <p>规则按当前顺序写入 Prompt，可直接调整优先顺序。</p>
                    </div>
                  </div>
                  <el-tag type="info">{{ promptTemplate.rules.length }} 条</el-tag>
                </header>

                <div class="prompt-rule-list">
                  <div
                    v-for="(rule, index) in promptTemplate.rules"
                    :key="index"
                    class="prompt-rule-row"
                    :class="{ 'has-error': !rule.trim() }"
                  >
                    <span class="rule-index">{{ index + 1 }}</span>
                    <el-input
                      v-model="promptTemplate.rules[index]"
                      :aria-label="`识别规则 ${index + 1}`"
                      type="textarea"
                      :autosize="{ minRows: 1, maxRows: 4 }"
                      @input="markDirty"
                    />
                    <div class="rule-actions">
                      <el-button
                        link
                        :disabled="index === 0"
                        @click="movePromptRule(index, -1)"
                      >
                        上移
                      </el-button>
                      <el-button
                        link
                        :disabled="index === promptTemplate.rules.length - 1"
                        @click="movePromptRule(index, 1)"
                      >
                        下移
                      </el-button>
                      <el-button link type="danger" @click="removePromptRule(index)">
                        删除
                      </el-button>
                    </div>
                  </div>
                  <el-empty
                    v-if="!promptTemplate.rules.length"
                    description="尚未配置通用识别规则"
                    :image-size="64"
                  />
                </div>

                <div class="prompt-rule-add">
                  <el-input
                    v-model="newPromptRule"
                    aria-label="新增识别规则"
                    placeholder="输入一条独立、可执行的判断规则"
                    @keyup.enter="addPromptRule"
                  />
                  <el-button
                    type="primary"
                    plain
                    :disabled="!newPromptRule.trim()"
                    @click="addPromptRule"
                  >
                    添加规则
                  </el-button>
                </div>
              </article>

              <article class="prompt-config-card prompt-feature-toggle">
                <header class="prompt-card-heading">
                  <div>
                    <span class="prompt-step">03</span>
                    <div>
                      <h3>在 Prompt 中使用典型说法</h3>
                      <p>
                        开启后，把样例管理中已启用的说法放到对应 Route 或 Intent 下，帮助模型理解分类边界。
                      </p>
                    </div>
                  </div>
                  <el-switch
                    v-model="promptTemplate.include_examples"
                    aria-label="在 Prompt 中使用典型说法"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                    @change="markDirty"
                  />
                </header>
                <el-alert
                  :type="promptTemplate.include_examples ? 'success' : 'info'"
                  :closable="false"
                  :title="
                    promptTemplate.include_examples
                      ? `已启用，将使用 ${examples.filter((example) => example.enabled !== false).length} 条典型说法`
                      : '已关闭，样例数据仍会保留，可随时重新开启'
                  "
                />
              </article>
            </div>

            <aside class="prompt-composition-card">
              <span class="section-kicker">系统自动拼装</span>
              <h3>最终 Prompt 还包含</h3>
              <p>
                下列内容来自其他配置页面或运行时，提示词管理只负责全局指令。
              </p>
              <ul>
                <li
                  v-for="item in promptComposition"
                  :key="item.label"
                  :class="{ 'is-disabled': !item.enabled }"
                >
                  <span class="composition-check">{{ item.enabled ? "✓" : "—" }}</span>
                  <div>
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.detail }}</small>
                  </div>
                </li>
              </ul>
              <div class="composition-note">
                <strong>不会进入 Prompt</strong>
                <p>枚举型 Slot 的完整匹配词典由程序使用，只把已提取结果提供给模型辅助判断。</p>
              </div>
            </aside>
          </div>

          <article class="prompt-preview-workbench">
            <div class="preview-workbench-copy">
              <span class="prompt-step">04</span>
              <div>
                <h3>用一句真实表达检查最终 Prompt</h3>
                <p>
                  预览使用已保存的配置草稿，不调用模型，也不会影响当前线上版本。
                </p>
              </div>
            </div>
            <div class="preview-workbench-action">
              <el-input
                v-model="previewText"
                aria-label="Prompt 预览输入"
                placeholder="例如：膝盖有点疼，今天还能练腿吗？"
                @keyup.enter="showPreview"
              />
              <el-button
                type="primary"
                @click="showPreview"
                :disabled="busy || dirty || !previewText.trim()"
              >
                生成最终 Prompt
              </el-button>
            </div>
            <p v-if="dirty" class="preview-disabled-tip">
              请先保存到配置草稿，再生成与运行时一致的预览。
            </p>
          </article>
        </template>
      </section>
      <section v-else-if="section === 'releases'" class="config-editor">
        <div class="config-page-intro">
          <div>
            <span class="section-kicker">配置上线与版本恢复</span>
            <h2>发布经过校验的业务配置</h2>
            <p>
              配置草稿只有发布后才会影响正式意图识别。模型选择由模型管理独立控制，不参与业务配置发布。
            </p>
          </div>
          <el-button @click="reload" :disabled="busy">重新载入</el-button>
        </div>

        <div class="release-status-grid">
          <article class="release-status-card">
            <span>当前线上配置</span>
            <strong>{{ activeRelease?.version ?? "尚未发布" }}</strong>
            <small v-if="activeRelease">
              {{ formatLocalTime(activeRelease.created_at) }} · {{ activeRelease.note }}
            </small>
            <small v-else>正式识别暂时没有可用的业务配置。</small>
          </article>
          <article class="release-status-card">
            <span>配置草稿</span>
            <strong>{{ dirty ? "有未保存修改" : "已保存" }}</strong>
            <small>
              {{ dirty ? "请先保存，避免发布遗漏修改。" : "当前页面内容已写入配置草稿。" }}
            </small>
          </article>
          <article class="release-status-card">
            <span>配置校验</span>
            <strong>{{ validationPassed ? "校验通过" : "等待校验" }}</strong>
            <small>
              {{ validationPassed ? "可以查看变更并发布。" : "发布前需要检查结构和引用关系。" }}
            </small>
          </article>
        </div>

        <div class="release-flow">
          <div class="release-flow-step" :class="{ done: !dirty }">
            <span>1</span>
            <div><strong>保存草稿</strong><small>汇总所有配置页面的修改</small></div>
          </div>
          <div class="release-flow-step" :class="{ done: validationPassed }">
            <span>2</span>
            <div><strong>校验配置</strong><small>检查名称、结构和引用是否合法</small></div>
          </div>
          <div class="release-flow-step">
            <span>3</span>
            <div><strong>确认并发布</strong><small>查看修改摘要后切换线上版本</small></div>
          </div>
        </div>

        <div class="release-actions">
          <el-button type="primary" @click="save" :disabled="busy || !dirty">
            保存到配置草稿
          </el-button>
          <el-button @click="validate" :disabled="busy || dirty || !draft.draft_json">
            校验配置
          </el-button>
          <el-button
            type="success"
            @click="preparePublish"
            :disabled="busy || dirty || !validationPassed || !draft.draft_json"
          >
            查看变更并发布
          </el-button>
          <small v-if="dirty">发布不可用：存在未保存修改。</small>
          <small v-else-if="!validationPassed">发布不可用：请先完成配置校验。</small>
        </div>

        <div class="release-history-heading">
          <div>
            <h3>配置版本</h3>
            <p>历史版本不可修改；恢复后会生成草稿，需要重新校验和发布。</p>
          </div>
        </div>
        <el-table :data="releases" row-key="id" class="release-history-table">
          <el-table-column label="配置版本" min-width="180">
            <template #default="{ row }">
              <div class="release-version-cell">
                <strong>{{ row.version }}</strong>
                <el-tag v-if="row.id === activeId" type="success">当前生效</el-tag>
                <el-tag v-else type="info">历史版本</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="发布时间" min-width="170">
            <template #default="{ row }">{{ formatLocalTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="note" label="发布说明" min-width="240" />
          <el-table-column label="操作" width="250" align="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="showRelease(row)" :disabled="busy">
                查看配置
              </el-button>
              <el-button link @click="restore(row)" :disabled="busy || dirty">
                基于此版本恢复
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="release-pagination">
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
      v-model="exampleDialogVisible"
      :title="editingExampleIndex === null ? '新增典型说法' : '编辑典型说法'"
      width="620px"
      :close-on-click-modal="false"
    >
      <div class="dialog-form">
        <label>
          <span>用户说法</span>
          <el-input
            v-model="exampleForm.text"
            aria-label="典型用户说法"
            type="textarea"
            :rows="3"
            placeholder="例如：我今天想练胸"
          />
        </label>
        <div class="dialog-form-grid">
          <label>
            <span>期望 Route</span>
            <el-select
              v-model="exampleForm.route"
              aria-label="典型说法期望 Route"
              @change="changeExampleRoute"
            >
              <el-option
                v-for="route in routes"
                :key="route.name"
                :label="`${route.zh}（${route.name}）`"
                :value="route.name"
              />
            </el-select>
          </label>
          <label>
            <span>期望 Intent（可选）</span>
            <el-select
              v-model="exampleForm.intent"
              aria-label="典型说法期望 Intent"
              clearable
              placeholder="不选择时仅辅助 Route 判断"
            >
              <el-option
                v-for="intent in exampleIntentOptions"
                :key="intent.name"
                :label="`${intent.zh}（${intent.name}）`"
                :value="intent.name"
              />
            </el-select>
          </label>
        </div>
        <div class="example-form-status">
          <div>
            <strong>启用这条说法</strong>
            <small>停用后数据仍保留，但不会写入最终 Prompt。</small>
          </div>
          <el-switch v-model="exampleForm.enabled" />
        </div>
      </div>
      <template #footer>
        <el-button @click="exampleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyExampleForm">应用修改</el-button>
      </template>
    </el-dialog>
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
    <el-dialog
      v-model="slotDialogVisible"
      :title="editingSlotName ? '编辑 Slot' : '新增 Slot'"
      width="620px"
      :close-on-click-modal="false"
    >
      <div class="dialog-form">
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
        />
        <div class="form-help">
          Slot 决定需要提取哪类参数。文本型由 LLM 提取；枚举型由程序词典匹配。标识建议使用稳定的英文 snake_case。
        </div>
        <div class="dialog-form-grid">
          <label>
            <span>Slot 标识</span>
            <el-input
              v-model="slotForm.name"
              aria-label="Slot 标识"
              placeholder="例如 body_part"
            />
          </label>
          <label>
            <span>显示名称</span>
            <el-input
              v-model="slotForm.zh"
              aria-label="Slot 显示名称"
              placeholder="例如 身体部位"
            />
          </label>
        </div>
        <label>
          <span>提取内容说明</span>
          <el-input
            v-model="slotForm.description"
            aria-label="Slot 说明"
            type="textarea"
            :rows="3"
            placeholder="说明这个参数表示什么，帮助模型判断是否需要提取"
          />
        </label>
        <label>
          <span>取值类型</span>
          <el-radio-group v-model="slotForm.value_type" aria-label="Slot 取值类型">
            <el-radio-button label="string">LLM 提取文本</el-radio-button>
            <el-radio-button label="enum">程序匹配枚举</el-radio-button>
          </el-radio-group>
          <small>
            {{
              slotForm.value_type === "enum"
                ? "程序使用 canonical、display 和 aliases 匹配原话；完整词典不进入 Prompt。"
                : "名称、说明和参考示例进入 Prompt；LLM 可以提取未配置的新文本。"
            }}
          </small>
        </label>
        <label>
          <span>词组父级</span>
          <el-input
            :model-value="slotForm.enum_group || slotForm.name"
            aria-label="Slot 词组父级"
            placeholder="保存时自动使用 Slot 标识创建"
            disabled
          />
          <small>
            新增 Slot 时自动创建；之后可在 Enum / Alias 页面维护
            {{ slotForm.value_type === "enum" ? "程序匹配词典" : "LLM 参考示例" }}。
          </small>
        </label>
        <div class="switch-field">
          <div>
            <strong>启用此 Slot</strong>
            <small>
              {{
                slotForm.value_type === "enum"
                  ? "停用后程序不再匹配该枚举参数。"
                  : "停用后该 Slot 不会进入 Prompt，模型返回也会被拒绝。"
              }}
            </small>
          </div>
          <el-switch v-model="slotForm.enabled" aria-label="启用此 Slot" />
        </div>
      </div>
      <template #footer>
        <el-button @click="slotDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applySlotForm">应用修改</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="enumGroupDialogVisible"
      :title="editingEnumGroupName ? '重命名 Enum Group' : '新增 Enum Group'"
      width="500px"
      :close-on-click-modal="false"
    >
      <div class="dialog-form">
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
        />
        <div class="form-help">
          每个 Slot 都有一个词组父级：文本型存放 LLM 参考示例，枚举型存放程序匹配词典。
        </div>
        <label>
          <span>Group 标识</span>
          <el-input
            v-model="enumGroupNameInput"
            aria-label="Enum Group 标识"
            placeholder="例如 body_part"
            @keyup.enter="applyEnumGroupForm"
          />
          <small v-if="editingEnumGroupName">
            重命名会同步更新引用此 Group 的 Slot，保存草稿时一并提交。
          </small>
        </label>
      </div>
      <template #footer>
        <el-button @click="enumGroupDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyEnumGroupForm">应用修改</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="enumValueDialogVisible"
      :title="
        selectedGroupIsText
          ? editingEnumValueIndex === null
            ? '新增参考示例'
            : '编辑参考示例'
          : editingEnumValueIndex === null
            ? '新增程序匹配值'
            : '编辑程序匹配值'
      "
      width="620px"
      :close-on-click-modal="false"
    >
      <div class="dialog-form">
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
        />
        <div class="form-help">
          当前父级：<code>{{ selectedEnumSlot?.name || selectedEnumGroup }}</code>。
          {{
            selectedGroupIsText
              ? "参考示例会帮助 LLM 理解可能出现的表达，但不会限制文本型 Slot 的输出。"
              : "这些值由程序直接匹配，不进入 LLM Prompt；同一表达不能归属于两个标准值。"
          }}
        </div>
        <div
          class="dialog-form-grid"
          :class="{ 'single-column': selectedGroupIsText }"
        >
          <label v-if="!selectedGroupIsText">
            <span>标准值 canonical</span>
            <el-input
              v-model="enumValueForm.canonical"
              aria-label="枚举标准值"
              placeholder="例如 knee"
            />
            <small>程序匹配成功后提供给下游系统的稳定值。</small>
          </label>
          <label>
            <span>{{ selectedGroupIsText ? "参考示例" : "显示名称 display" }}</span>
            <el-input
              v-model="enumValueForm.display"
              :aria-label="selectedGroupIsText ? '参考示例' : '枚举显示名称'"
              :placeholder="selectedGroupIsText ? '例如 杠铃上斜卧推' : '例如 膝盖'"
            />
            <small>
              {{
                selectedGroupIsText
                  ? "这是示例，不代表模型只能提取这个词组。"
                  : "既用于业务展示，也作为程序匹配表达。"
              }}
            </small>
          </label>
        </div>
        <label>
          <span>{{ selectedGroupIsText ? "相近说法" : "可识别说法 aliases" }}</span>
          <div class="alias-input-row">
            <el-input
              v-model="enumAliasInput"
              aria-label="枚举别名"
              :placeholder="
                selectedGroupIsText
                  ? '输入其他示例；支持逗号分隔'
                  : '输入膝、膝关节；支持逗号分隔'
              "
              @keyup.enter="addEnumAlias"
            />
            <el-button @click="addEnumAlias" :disabled="!enumAliasInput.trim()">
              添加
            </el-button>
          </div>
          <div v-if="enumValueForm.aliases.length" class="editable-tag-list">
            <el-tag
              v-for="(alias, index) in enumValueForm.aliases"
              :key="`${alias}-${index}`"
              closable
              @close="removeEnumAlias(index)"
            >
              {{ alias }}
            </el-tag>
          </div>
          <small v-else>
            {{
              selectedGroupIsText
                ? "暂无相近说法。"
                : "暂无别名；程序仍会匹配 canonical 和 display。"
            }}
          </small>
        </label>
        <div class="switch-field">
          <div>
            <strong>
              {{ selectedGroupIsText ? "启用此参考示例" : "启用此程序匹配值" }}
            </strong>
            <small>
              {{
                selectedGroupIsText
                  ? "停用后不再作为示例进入 Prompt，但不会限制其他文本输出。"
                  : "停用后程序不再使用该标准值、显示名称和别名进行匹配。"
              }}
            </small>
          </div>
          <el-switch
            v-model="enumValueForm.enabled"
            aria-label="启用此枚举值"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="enumValueDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyEnumValueForm">应用修改</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="previewVisible" :title="previewTitle" width="760px">
      <pre class="prompt-view">{{ preview }}</pre>
    </el-dialog>
    <el-dialog v-model="detailVisible" title="配置版本详情" width="680px">
      <div v-if="detail" class="release-detail">
        <div class="release-detail-heading">
          <div>
            <span>配置版本</span>
            <strong>{{ detail.version }}</strong>
          </div>
          <el-tag :type="detail.id === activeId ? 'success' : 'info'">
            {{ detail.id === activeId ? "当前生效" : "历史版本" }}
          </el-tag>
        </div>
        <dl class="release-detail-meta">
          <div>
            <dt>发布时间</dt>
            <dd>{{ formatLocalTime(detail.created_at) }}</dd>
          </div>
          <div>
            <dt>发布说明</dt>
            <dd>{{ detail.note }}</dd>
          </div>
        </dl>
        <div class="release-detail-section">
          <h4>包含的业务配置</h4>
          <div class="release-detail-grid">
            <article v-for="item in releaseDetailSections" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="confirmVisible"
      title="确认发布业务配置"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="summary">
        <div class="publish-confirm-copy">
          <p>发布后，正式意图识别会立即使用这份业务配置；模型选择不会改变。</p>
          <div class="publish-change-summary">
            <strong>本次配置变更</strong>
            <ul v-if="summary.changes.length">
              <li v-for="change in summary.changes" :key="change.section">
                {{ changeDescription(change) }}
              </li>
            </ul>
            <p v-else>未检测到业务配置变化，仍会创建一个新的配置版本。</p>
          </div>
          <label class="publish-note-field">
            <span>发布说明 <em>必填</em></span>
            <el-input
              v-model="note"
              aria-label="发布说明"
              placeholder="例如：调整训练计划意图说明，补充全局输出规则"
              maxlength="4000"
              show-word-limit
              type="textarea"
              :rows="4"
            />
          </label>
        </div>
      </template>
      <template #footer
        ><el-button @click="confirmVisible = false" :disabled="busy"
          >取消</el-button
        ><el-button
          type="primary"
          @click="publish"
          :disabled="busy || !note.trim()"
          >确认发布</el-button
        ></template
      >
    </el-dialog>
  </section>
</template>
