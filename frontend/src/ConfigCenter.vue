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
  type SlotDefinition,
  type EnumValueDefinition,
  type PromptModule,
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
const editors = reactive({
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
const isParameterSection = computed(
  () => props.section === "slots" || props.section === "enums",
);

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
    examples.value = structuredClone(value.draft_json.examples);
    for (const key of Object.keys(editors) as (keyof typeof editors)[])
      editors[key] = pretty(value.draft_json[key]);
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
  summary.value = undefined;
}
function draftPayload(): DraftJson {
  const result: Record<string, unknown> = {
    schema_version: 1,
    routes: routes.value,
    intents: intents.value,
    slots: slots.value,
    enums: enumGroups.value,
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
    message.value = isParameterSection.value
      ? "配置草稿已保存，发布前不会影响线上识别"
      : "配置已保存";
  });
}
async function validate() {
  await run(async () => {
    await configApi.validate();
    message.value = "校验通过：配置结构、名称和引用合法";
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
        <p v-if="isParameterSection">
          页面编辑 → 保存到配置草稿 → 校验与预览 → 发布后线上生效
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
        isParameterSection
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
      v-if="draft.draft_json && !isPromptConfigSection"
      class="toolbar"
    >
      <el-button type="primary" @click="save" :disabled="busy || !dirty"
        >{{ isParameterSection ? "保存到配置草稿" : "保存配置" }}</el-button
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
