<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { ElMessage } from "element-plus";
import {
  configApi,
  ConfigApiError,
  request,
  type DraftJson,
  type Release,
} from "./configApi";
import { modelApi, type ManagedModel } from "./modelApi";
import {
  evaluationApi as api,
  downloadEvaluation,
  filterQuery,
  type Comparison,
  type Dataset,
  type EvaluationCase,
  type EvaluationResult,
  type Filters,
  type Run,
  type RunInput,
} from "./evaluationApi";
import EvaluationExpectedEditor from "./EvaluationExpectedEditor.vue";
import EvaluationResultView from "./EvaluationResultView.vue";
import "./evaluation.css";

const tab = ref("runs");
const datasets = ref<Dataset[]>([]);
const runs = ref<Run[]>([]);
const datasetTotal = ref(0),
  runTotal = ref(0);
const models = ref<ManagedModel[]>([]);
const releases = ref<Release[]>([]);
const configuration = ref<DraftJson | null>(null);
const defaultModel = ref("");
const error = ref("");
const busy = ref(false);
const detailLoading = ref(false);
const selectedRun = ref<Run | null>(null);
const results = ref<EvaluationResult[]>([]);
const resultTotal = ref(0),
  page = ref(1);
const filteredCaseIds = ref<string[]>([]);
const availableTags = ref<string[]>([]),
  availableIssues = ref<string[]>([]);
const checkedRows = ref<EvaluationResult[]>([]);
const filters = reactive<Filters>({
  status: "",
  tag: "",
  issue: "",
  keyword: "",
  bad_only: false,
  primary_only: true,
});
const summary = computed(() => selectedRun.value?.summary);
const labels: Record<string, string> = {
  pass: "通过",
  fail: "不通过",
  error: "执行错误",
  review: "待复核",
  not_run: "未执行",
  judging: "评审中",
  queued: "排队中",
  running: "运行中",
  completed: "执行结束",
  cancelled: "已取消",
  failed: "任务中断",
};
const issueLabels: Record<string, string> = {
  action_missing: "漏动作",
  action_extra: "多动作",
  route: "路由错误",
  intent: "意图错误",
  slot: "参数错误",
  dependency: "依赖错误",
  composition: "组合方式错误",
  risk: "风险错误",
  clarification: "追问错误",
  execution_error: "执行错误",
  judge_error: "评审错误",
  ambiguous_standard: "标准不明确",
  other: "其他问题",
};
const dimensionLabels: Record<string, string> = {
  intent: "二级意图",
  slots: "动作参数",
  composition: "组合方式",
  clarification: "追问",
  risk: "风险",
};
const ratioLabel = (value: number | null) =>
  value === null ? "未标注 / 不适用" : `${(value * 100).toFixed(1)}%`;
const statusType = (
  status: string,
): "success" | "danger" | "warning" | "info" =>
  status === "pass"
    ? "success"
    : ["fail", "error", "failed"].includes(status)
      ? "danger"
      : ["review", "judging"].includes(status)
        ? "warning"
        : "info";
const dateLabel = (value: string) =>
  new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString("zh-CN");
let disposed = false,
  refreshVersion = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

function errorText(cause: unknown) {
  if (cause instanceof ConfigApiError && cause.issues.length) {
    return `${cause.message}\n${cause.issues.map((issue) => `${issue.field}：${issue.message}`).join("\n")}`;
  }
  return cause instanceof Error ? cause.message : "操作失败，请重试";
}
async function act(callback: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await callback();
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}
async function loadLists() {
  const [data, tasks] = await Promise.all([api.datasets(), api.runs()]);
  if (disposed) return;
  datasets.value = data.items;
  datasetTotal.value = data.total;
  runs.value = tasks.items;
  runTotal.value = tasks.total;
}
async function loadMoreDatasets() {
  await act(async () => {
    const response = await api.datasets(datasets.value.length);
    datasets.value.push(...response.items);
    datasetTotal.value = response.total;
  });
}
async function loadMoreRuns() {
  await act(async () => {
    const response = await api.runs(runs.value.length);
    runs.value.push(...response.items);
    runTotal.value = response.total;
  });
}
async function refreshDetail() {
  const id = selectedRun.value?.id;
  if (!id) return;
  const version = ++refreshVersion;
  detailLoading.value = true;
  try {
    const [task, records] = await Promise.all([
      api.run(id),
      api.results(id, { ...filters }, (page.value - 1) * 50),
    ]);
    if (disposed || selectedRun.value?.id !== id || version !== refreshVersion)
      return;
    selectedRun.value = task;
    results.value = records.items;
    resultTotal.value = records.total;
    filteredCaseIds.value = records.case_ids;
    availableTags.value = records.tags;
    availableIssues.value = records.issue_tags;
    if (selectedResult.value) {
      const updated = records.items.find(
        (item) => item.id === selectedResult.value?.id,
      );
      if (updated && !reviewDirty.value) selectedResult.value = updated;
    }
  } finally {
    if (version === refreshVersion) detailLoading.value = false;
  }
}
async function selectRun(run: Run) {
  ++refreshVersion;
  selectedRun.value = run;
  results.value = [];
  page.value = 1;
  selectedResult.value = null;
  checkedRows.value = [];
  window.history.replaceState({}, "", `/evaluation?run=${run.id}`);
  if (!datasets.value.some((item) => item.id === run.dataset_id)) {
    datasets.value.push(await api.dataset(run.dataset_id));
  }
  if (!runs.value.some((item) => item.id === run.id)) runs.value.unshift(run);
  await refreshDetail();
}
async function filterChanged() {
  page.value = 1;
  checkedRows.value = [];
  await act(refreshDetail);
}
function resetFilters() {
  Object.assign(filters, {
    status: "",
    tag: "",
    issue: "",
    keyword: "",
    bad_only: false,
    primary_only: true,
  });
  void filterChanged();
}
function backToRuns() {
  ++refreshVersion;
  selectedRun.value = null;
  selectedResult.value = null;
  window.history.replaceState({}, "", "/evaluation");
  void act(loadLists);
}

const importOpen = ref(false),
  importName = ref(""),
  importFile = ref<File | null>(null);
function pickFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  importFile.value = file ?? null;
  if (file && !importName.value)
    importName.value = file.name.replace(/\.xlsx$/i, "");
}
async function importDataset() {
  await act(async () => {
    if (!importName.value.trim() || !importFile.value)
      throw new Error("请填写评测集名称并选择 Excel 文件");
    await api.importDataset(importName.value, importFile.value);
    importOpen.value = false;
    importFile.value = null;
    importName.value = "";
    await loadLists();
    ElMessage.success("评测集已导入，可查看标准答案或创建评测任务");
  });
}

const editorOpen = ref(false),
  editorName = ref(""),
  editingCases = ref<EvaluationCase[]>([]),
  editingIndex = ref(0);
const editingCase = computed(() => editingCases.value[editingIndex.value]);
function blankCase(): EvaluationCase {
  return {
    case_id: `case_${Date.now()}_${editingCases.value.length + 1}`,
    question: "",
    standard_answer: "",
    tags: [],
    critical: false,
  };
}
function openEditor() {
  editorName.value = "";
  editingCases.value = [blankCase()];
  editingIndex.value = 0;
  editorOpen.value = true;
}
async function editDataset(dataset: Dataset) {
  await act(async () => {
    const data = await api.dataset(dataset.id);
    editorName.value = data.name;
    editingCases.value = data.cases;
    editingIndex.value = 0;
    editorOpen.value = true;
  });
}
function removeCase() {
  editingCases.value.splice(editingIndex.value, 1);
  if (!editingCases.value.length) editingCases.value.push(blankCase());
  editingIndex.value = Math.min(
    editingIndex.value,
    editingCases.value.length - 1,
  );
}
async function saveDataset() {
  await act(async () => {
    if (!editorName.value.trim()) throw new Error("请填写评测集名称");
    if (
      editingCases.value.some(
        (item) => !item.question.trim() || !item.standard_answer.trim(),
      )
    )
      throw new Error("每条用例都需要填写问题和标准答案");
    await api.createDataset(editorName.value, editingCases.value);
    editorOpen.value = false;
    await loadLists();
    ElMessage.success("已保存为新的评测集版本，原任务结果保留");
  });
}

const createOpen = ref(false);
const createForm = reactive<RunInput>({
  name: "",
  dataset_id: 0,
  release_id: null,
  model_uid: "",
  judge_model_uid: null,
  repeat_count: 1,
  worker_concurrency: 2,
  pass_threshold: 100,
});
const createCaseCount = computed(
  () =>
    createForm.case_ids?.length ??
    datasets.value.find((item) => item.id === createForm.dataset_id)
      ?.case_count ??
    0,
);
function openCreate(dataset?: Dataset, ids?: string[]) {
  const parent = ids ? selectedRun.value : null;
  Object.assign(createForm, {
    name: parent
      ? `${parent.name} · 复测`
      : dataset
        ? `${dataset.name} · 评测`
        : "",
    dataset_id: parent?.dataset_id ?? dataset?.id ?? datasets.value[0]?.id ?? 0,
    model_uid: parent?.model_uid ?? defaultModel.value,
    judge_model_uid: parent?.judge_model_uid ?? null,
    release_id: 0,
    repeat_count: 1,
    worker_concurrency: 2,
    pass_threshold: parent?.pass_threshold ?? 100,
    parent_run_id: parent?.id,
    case_ids: ids,
  });
  createOpen.value = true;
}
async function submitRun() {
  await act(async () => {
    if (
      !createForm.name.trim() ||
      !createForm.dataset_id ||
      !createForm.model_uid
    )
      throw new Error("请填写任务名称、评测集和识别模型");
    const run = await api.createRun({
      ...createForm,
      release_id: createForm.release_id || null,
      judge_model_uid: createForm.judge_model_uid || null,
    });
    createOpen.value = false;
    tab.value = "runs";
    await loadLists();
    await selectRun(run);
    ElMessage.success("任务已排队，独立 Worker 将在后台执行");
  });
}
const selectedResult = ref<EvaluationResult | null>(null);
const reviewReason = ref(""),
  reviewer = ref(""),
  reviewDirty = ref(false);
const canReview = computed(
  () =>
    selectedResult.value?.id != null &&
    ["pass", "fail", "review"].includes(selectedResult.value.status) &&
    !selectedResult.value.verdict.rules?.issues.length,
);
function openResult(row: EvaluationResult) {
  selectedResult.value = row;
  reviewReason.value = "";
  reviewDirty.value = false;
}
async function review(decision: "pass" | "fail") {
  await act(async () => {
    if (!selectedRun.value || !selectedResult.value) return;
    if (!reviewReason.value.trim() || !reviewer.value.trim())
      throw new Error("请填写复核人和具体复核理由");
    await api.review(
      selectedRun.value.id,
      selectedResult.value,
      decision,
      reviewReason.value,
      reviewer.value,
    );
    reviewDirty.value = false;
    selectedResult.value = null;
    await refreshDetail();
    ElMessage.success("复核已保存，通过率已重新计算");
  });
}
const traceOpen = ref(false),
  traceData = ref<unknown>(null);
async function inspectTrace() {
  await act(async () => {
    if (!selectedResult.value?.trace_id) return;
    traceData.value = await request(`/traces/${selectedResult.value.trace_id}`);
    traceOpen.value = true;
  });
}
async function exportResults() {
  await act(async () => {
    if (!selectedRun.value) return;
    await downloadEvaluation(
      `/runs/${selectedRun.value.id}/export?${filterQuery(filters)}`,
      `${selectedRun.value.name}-评测结果.xlsx`,
    );
  });
}
const compareOpen = ref(false),
  compareLeft = ref<number | null>(null),
  compareRight = ref<number | null>(null);
const comparison = ref<Comparison | null>(null),
  changeFilter = ref("");
const compareRows = computed(
  () =>
    comparison.value?.changes.filter(
      (item) => !changeFilter.value || item.change === changeFilter.value,
    ) ?? [],
);
async function compare() {
  await act(async () => {
    if (
      !compareLeft.value ||
      !compareRight.value ||
      compareLeft.value === compareRight.value
    )
      throw new Error("请选择两个不同的任务");
    comparison.value = await api.compare(compareLeft.value, compareRight.value);
  });
}
watch([compareLeft, compareRight], () => {
  comparison.value = null;
});

async function poll() {
  if (disposed) return;
  try {
    if (
      !busy.value &&
      !detailLoading.value &&
      selectedRun.value &&
      ["queued", "running"].includes(selectedRun.value.status)
    )
      await refreshDetail();
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    if (!disposed) timer = setTimeout(() => void poll(), 3000);
  }
}
onMounted(async () => {
  await act(async () => {
    const outcomes = await Promise.allSettled([
      loadLists(),
      modelApi.list(),
      configApi.releases(),
    ]);
    const modelResult = outcomes[1],
      releaseResult = outcomes[2];
    if (modelResult.status === "fulfilled") {
      models.value = modelResult.value.items;
      defaultModel.value =
        modelResult.value.default_model_uid ??
        models.value.find((item) => item.enabled)?.model_uid ??
        "";
    }
    if (releaseResult.status === "fulfilled") {
      releases.value = releaseResult.value.items;
      if (releaseResult.value.active_release_id) {
        const release = await configApi.release(
          releaseResult.value.active_release_id,
        );
        configuration.value = release.snapshot_json ?? null;
      }
    }
    for (const outcome of outcomes)
      if (outcome.status === "rejected") throw outcome.reason;
    const requested = Number(
      new URLSearchParams(window.location.search).get("run"),
    );
    if (requested > 0) await selectRun(await api.run(requested));
  });
  void poll();
});
onBeforeUnmount(() => {
  disposed = true;
  ++refreshVersion;
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <section class="evaluation-workbench">
    <div class="eval-intro">
      <div>
        <h2>用标准答案验证识别效果</h2>
        <p>填写问题与标准答案，批量执行后查看通过率，定位并复测 badcase。</p>
      </div>
      <el-button
        :loading="busy"
        @click="
          act(() =>
            downloadEvaluation('/template', 'AI_Coach_批量评测模板.xlsx'),
          )
        "
        >下载评测模板</el-button
      >
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="eval-error"
      @close="error = ''"
    />
    <template v-if="!selectedRun">
      <el-tabs v-model="tab">
        <el-tab-pane label="评测任务" name="runs">
          <div class="eval-toolbar">
            <span class="muted">后台持久执行，关闭页面后任务继续。</span>
            <div>
              <el-button @click="act(loadLists)">刷新</el-button
              ><el-button @click="compareOpen = true">对比任务</el-button
              ><el-button
                type="primary"
                :disabled="!datasets.length"
                @click="openCreate()"
                >新建评测任务</el-button
              >
            </div>
          </div>
          <el-table
            :data="runs"
            row-key="id"
            empty-text="还没有评测任务，先在评测集页填写或导入标准答案"
          >
            <el-table-column label="任务" min-width="220"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  @click="act(() => selectRun(row))"
                  >{{ row.name }}</el-button
                >
                <div class="muted">
                  {{ dateLabel(row.created_at) }}
                </div></template
              ></el-table-column
            >
            <el-table-column label="识别 / 评审" min-width="180"
              ><template #default="{ row }"
                >{{ row.model_label }}
                <div class="muted">{{ row.judge_label }}</div></template
              ></el-table-column
            >
            <el-table-column label="进度" min-width="150"
              ><template #default="{ row }"
                ><el-progress
                  :percentage="
                    Math.round(
                      (row.progress.completed * 100) / row.execution_count,
                    )
                  "
                /><small
                  >{{ row.progress.completed }} /
                  {{ row.execution_count }} 次</small
                ></template
              ></el-table-column
            >
            <el-table-column label="状态" width="120"
              ><template #default="{ row }"
                ><el-tag :type="statusType(row.status)">{{
                  labels[row.status]
                }}</el-tag></template
              ></el-table-column
            >
            <el-table-column label="查看" width="100"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  @click="act(() => selectRun(row))"
                  >查看结果</el-button
                ></template
              ></el-table-column
            >
          </el-table>
          <el-button
            v-if="runs.length < runTotal"
            class="eval-more"
            @click="loadMoreRuns"
            >加载更多任务</el-button
          >
        </el-tab-pane>
        <el-tab-pane label="评测集与标准答案" name="datasets">
          <div class="eval-toolbar">
            <span class="muted"
              >保存修改会创建新版本，历史评测保留当时的标准答案。</span
            >
            <div>
              <el-button @click="importOpen = true">导入 Excel</el-button
              ><el-button type="primary" @click="openEditor"
                >页面填写</el-button
              >
            </div>
          </div>
          <el-table
            :data="datasets"
            row-key="id"
            empty-text="下载模板，只需填写问题、标准答案两列即可导入"
          >
            <el-table-column prop="name" label="评测集" min-width="200" />
            <el-table-column prop="case_count" label="用例数" width="90" />
            <el-table-column label="保存时间" min-width="170"
              ><template #default="{ row }">{{
                dateLabel(row.created_at)
              }}</template></el-table-column
            >
            <el-table-column label="操作" min-width="300"
              ><template #default="{ row }">
                <el-button link type="primary" @click="editDataset(row)"
                  >查看 / 编辑新版本</el-button
                >
                <el-button
                  link
                  @click="
                    act(() =>
                      downloadEvaluation(
                        `/datasets/${row.id}/export`,
                        `${row.name}.xlsx`,
                      ),
                    )
                  "
                  >下载</el-button
                >
                <el-button link type="primary" @click="openCreate(row)"
                  >开始评测</el-button
                >
              </template></el-table-column
            >
          </el-table>
          <el-button
            v-if="datasets.length < datasetTotal"
            class="eval-more"
            @click="loadMoreDatasets"
            >加载更多评测集</el-button
          >
        </el-tab-pane>
      </el-tabs>
    </template>

    <template v-else>
      <div class="eval-toolbar">
        <div>
          <el-button link @click="backToRuns">← 返回任务列表</el-button>
          <h2>{{ selectedRun.name }}</h2>
          <p class="muted">
            {{ selectedRun.model_label }} · 评审：{{
              selectedRun.judge_label
            }}
            · 每条 {{ selectedRun.repeat_count }} 次
          </p>
        </div>
        <div>
          <el-tag>{{ labels[selectedRun.status] }}</el-tag
          ><el-button :loading="detailLoading" @click="act(refreshDetail)"
            >刷新</el-button
          >
          <el-button
            v-if="['queued', 'running'].includes(selectedRun.status)"
            :disabled="selectedRun.cancel_requested"
            @click="
              act(async () => {
                await api.cancel(selectedRun!.id);
                await refreshDetail();
              })
            "
            >{{
              selectedRun.cancel_requested ? "等待当前用例收尾" : "取消后续执行"
            }}</el-button
          >
          <el-button
            @click="
              compareLeft = selectedRun.id;
              compareOpen = true;
            "
            >对比任务</el-button
          >
        </div>
      </div>
      <el-alert
        v-if="selectedRun.error"
        :title="selectedRun.error"
        type="error"
        :closable="false"
      />
      <el-alert
        v-if="selectedRun.status === 'queued'"
        title="任务等待 Worker 领取；如果长时间未开始，请检查评测 Worker 是否已启动。"
        type="info"
        :closable="false"
      />
      <div v-if="summary" class="eval-summary">
        <div class="eval-rate" :class="{ final: summary.final }">
          <span>{{
            summary.final ? "最终通过率" : "当前通过率 · 验收未完成"
          }}</span
          ><strong>{{ summary.pass_rate }}<small>%</small></strong>
          <p>{{ summary.passed }} / {{ summary.total }} 条通过</p>
        </div>
        <div class="eval-counts">
          <div>
            <b>{{ summary.passed }}</b
            >通过
          </div>
          <div>
            <b>{{ summary.failed }}</b
            >不通过
          </div>
          <div>
            <b>{{ summary.errors }}</b
            >执行错误
          </div>
          <div>
            <b>{{ summary.review }}</b
            >待复核
          </div>
          <div>
            <b>{{ summary.not_run }}</b
            >未执行
          </div>
        </div>
        <div class="eval-acceptance">
          <el-tag
            size="large"
            :type="
              summary.acceptance === 'passed'
                ? 'success'
                : summary.acceptance === 'failed'
                  ? 'danger'
                  : 'warning'
            "
            >{{
              summary.acceptance === "passed"
                ? "验收达标"
                : summary.acceptance === "failed"
                  ? "验收未达标"
                  : "验收未完成"
            }}</el-tag
          >
          <p>目标通过率 ≥ {{ selectedRun.pass_threshold }}%</p>
          <p>关键用例未通过次数：{{ summary.critical_failures }}</p>
        </div>
      </div>
      <p v-if="summary" class="muted">
        通过率 = 首次执行最终通过的用例数 ÷
        全部用例数。执行错误仍计入分母。全部重复执行及待复核处理完毕后才生成最终结论。
      </p>
      <div v-if="summary" class="eval-secondary-metrics">
        <span v-if="summary.judging">{{ summary.judging }} 条正在评审</span>
        <span>已记录 Token {{ summary.recorded_tokens }}</span>
        <span
          >执行 {{ summary.completed_executions }}/{{
            summary.total_executions
          }}
          次</span
        ><span>平均 {{ summary.average_latency_ms ?? "—" }} ms</span
        ><span>P95 {{ summary.p95_latency_ms ?? "—" }} ms</span>
        <span v-if="selectedRun.repeat_count > 1"
          >结构化结果稳定率 {{ summary.stability_rate ?? "—" }}%</span
        >
      </div>
      <el-collapse v-if="summary" class="eval-quality">
        <el-collapse-item title="查看场景通过率与精确检查指标" name="quality">
          <div class="eval-toolbar">
            <el-button
              v-for="(entry, tag) in summary.by_tag"
              :key="tag"
              @click="
                filters.tag = String(tag) === '未分类' ? '' : String(tag);
                filterChanged();
              "
              >{{ tag }}：{{ entry.passed }}/{{ entry.total }} 通过</el-button
            >
          </div>
          <p class="muted">
            以下指标仅统计填写了对应精确标准的首次执行；未填写不会当作正确。动作路由标注覆盖
            {{ summary.quality.labelled_cases }}/{{ summary.total }}
            条。漏动作和执行错误计入未识别，多动作计入误识别。
          </p>
          <div class="eval-secondary-metrics">
            <span v-for="(entry, key) in summary.quality.dimensions" :key="key"
              >{{ dimensionLabels[String(key)] }}：{{
                entry.checked
                  ? `${entry.passed}/${entry.checked} 正确`
                  : "未标注"
              }}</span
            ><span>Macro-F1：{{ ratioLabel(summary.quality.macro_f1) }}</span>
          </div>
          <el-table
            v-if="summary.quality.per_route.length"
            :data="summary.quality.per_route"
            size="small"
            ><el-table-column prop="route" label="路由" /><el-table-column
              prop="support"
              label="期望动作数"
            /><el-table-column label="Precision"
              ><template #default="{ row }">{{
                ratioLabel(row.precision)
              }}</template></el-table-column
            ><el-table-column label="Recall"
              ><template #default="{ row }">{{
                ratioLabel(row.recall)
              }}</template></el-table-column
            ><el-table-column label="F1"
              ><template #default="{ row }">{{
                ratioLabel(row.f1)
              }}</template></el-table-column
            ></el-table
          >
          <el-table
            v-if="summary.quality.confusion.length"
            :data="summary.quality.confusion"
            size="small"
            ><el-table-column
              prop="expected"
              label="期望路由" /><el-table-column
              prop="actual"
              label="实际路由" /><el-table-column
              prop="count"
              label="动作数（混淆矩阵非零项）"
          /></el-table>
        </el-collapse-item>
      </el-collapse>
      <div class="eval-filters">
        <el-checkbox v-model="filters.bad_only" border @change="filterChanged"
          >只看 badcase / 待复核</el-checkbox
        >
        <el-select
          v-model="filters.status"
          placeholder="全部判定"
          clearable
          @change="filterChanged"
          ><el-option
            v-for="key in [
              'pass',
              'fail',
              'error',
              'review',
              'judging',
              'not_run',
              'cancelled',
            ]"
            :key="key"
            :label="labels[key]"
            :value="key"
        /></el-select>
        <el-select
          v-model="filters.issue"
          placeholder="问题类别"
          clearable
          @change="filterChanged"
          ><el-option
            v-for="issue in availableIssues"
            :key="issue"
            :label="issueLabels[issue] ?? issue"
            :value="issue"
        /></el-select>
        <el-select
          v-model="filters.tag"
          placeholder="场景标签"
          clearable
          @change="filterChanged"
          ><el-option
            v-for="tag in availableTags"
            :key="tag"
            :label="tag"
            :value="tag"
        /></el-select>
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索问题、答案或失败原因"
          @keyup.enter="filterChanged"
          @clear="filterChanged"
        />
        <el-button @click="filterChanged">筛选</el-button
        ><el-button link @click="resetFilters">重置</el-button>
        <el-checkbox v-model="filters.primary_only" @change="filterChanged"
          >只看首次执行</el-checkbox
        >
      </div>
      <div class="eval-toolbar">
        <span class="muted"
          >当前筛选 {{ resultTotal }} 条执行记录、{{
            filteredCaseIds.length
          }}
          个用例</span
        >
        <div>
          <el-button :disabled="!resultTotal" @click="exportResults"
            >导出当前筛选</el-button
          >
          <el-button
            :disabled="!checkedRows.length"
            @click="
              openCreate(undefined, [
                ...new Set(checkedRows.map((row) => row.case_id)),
              ])
            "
            >复测选中用例</el-button
          >
          <el-button
            type="primary"
            :disabled="!filteredCaseIds.length"
            @click="openCreate(undefined, filteredCaseIds)"
            >复测筛选结果</el-button
          >
        </div>
      </div>
      <el-table
        :data="results"
        :row-key="
          (row: EvaluationResult) => `${row.case_id}:${row.repeat_index}`
        "
        @selection-change="checkedRows = $event"
        empty-text="没有符合筛选条件的结果"
      >
        <el-table-column type="selection" width="40" />
        <el-table-column label="问题 / 标准答案" min-width="300"
          ><template #default="{ row }"
            ><strong>{{ row.question }}</strong>
            <p class="eval-gold-snippet">{{ row.standard_answer }}</p>
            <small class="muted"
              >{{ row.case_id }} · 第 {{ row.repeat_index + 1 }} 次</small
            ><el-tag v-if="row.critical" size="small" type="warning"
              >关键</el-tag
            ></template
          ></el-table-column
        >
        <el-table-column label="判定" width="120"
          ><template #default="{ row }"
            ><el-tag :type="statusType(row.status)">{{
              labels[row.status]
            }}</el-tag>
            <div v-if="selectedRun.repeat_count > 1" class="muted">
              {{ row.repeat_passed ?? 0 }}/{{ selectedRun.repeat_count }} 次通过
            </div></template
          ></el-table-column
        >
        <el-table-column label="问题 / 评审理由" min-width="260"
          ><template #default="{ row }"
            ><div>
              <el-tag
                v-for="issue in row.issue_tags"
                :key="issue"
                size="small"
                type="info"
                >{{ issueLabels[issue] ?? issue }}</el-tag
              >
            </div>
            <p>{{ row.reason }}</p></template
          ></el-table-column
        >
        <el-table-column label="详情" width="100"
          ><template #default="{ row }"
            ><el-button link type="primary" @click="openResult(row)"
              >查看 / 复核</el-button
            ></template
          ></el-table-column
        >
      </el-table>
      <el-pagination
        v-model:current-page="page"
        :page-size="50"
        :total="resultTotal"
        layout="total, prev, pager, next"
        @current-change="act(refreshDetail)"
      />
    </template>

    <el-dialog
      v-model="importOpen"
      title="导入问题与标准答案"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="使用当前模板，必填列为问题、标准答案。结构化动作和参数工作表可以留空。"
        type="info"
        :closable="false"
      />
      <el-form label-position="top"
        ><el-form-item label="评测集名称"
          ><el-input v-model="importName" maxlength="128" /></el-form-item
        ><el-form-item label="Excel 文件"
          ><input type="file" accept=".xlsx" @change="pickFile" /></el-form-item
      ></el-form>
      <p v-if="error" class="eval-dialog-error">{{ error }}</p>
      <template #footer
        ><el-button @click="importOpen = false">关闭</el-button
        ><el-button type="primary" :loading="busy" @click="importDataset"
          >校验并导入</el-button
        ></template
      >
    </el-dialog>

    <el-dialog
      v-model="editorOpen"
      title="问题与标准答案 · 保存为新版本"
      width="min(1100px, 96vw)"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form label-position="top"
        ><el-form-item label="评测集名称"
          ><el-input v-model="editorName" maxlength="128"
        /></el-form-item>
        <div class="eval-toolbar">
          <span>{{ editingCases.length }} 条用例</span
          ><el-button
            :disabled="editingCases.length >= 500"
            @click="
              editingCases.push(blankCase());
              editingIndex = editingCases.length - 1;
            "
            >添加用例</el-button
          >
        </div>
        <div class="eval-case-editor">
          <aside>
            <button
              v-for="(item, index) in editingCases"
              :key="index"
              type="button"
              :class="{ active: editingIndex === index }"
              @click="editingIndex = index"
            >
              {{ index + 1 }}. {{ item.question || "未填写问题" }}
            </button>
          </aside>
          <div v-if="editingCase" class="eval-case-form">
            <div class="eval-form-grid">
              <el-form-item label="用例编号"
                ><el-input
                  v-model="editingCase.case_id"
                  maxlength="128" /></el-form-item
              ><el-form-item label="场景标签"
                ><el-select
                  v-model="editingCase.tags"
                  multiple
                  filterable
                  allow-create
                  default-first-option
              /></el-form-item>
            </div>
            <el-form-item label="问题（必填）"
              ><el-input
                v-model="editingCase.question"
                type="textarea"
                :rows="3"
                maxlength="2000"
                show-word-limit
            /></el-form-item>
            <el-form-item label="标准答案（必填）"
              ><el-input
                v-model="editingCase.standard_answer"
                type="textarea"
                :rows="5"
                maxlength="10000"
                show-word-limit
                placeholder="说明应该识别的动作、参数、先后关系，以及是否需要追问。"
            /></el-form-item>
            <el-checkbox v-model="editingCase.critical"
              >关键用例：任何一次未通过都会阻止验收达标</el-checkbox
            >
            <el-collapse
              ><el-collapse-item
                title="可选：精确检查动作、参数、风险与追问"
                name="expected"
                ><EvaluationExpectedEditor
                  v-model="editingCase.expected"
                  :configuration="configuration" /></el-collapse-item
            ></el-collapse>
            <el-button link type="danger" @click="removeCase"
              >删除当前用例</el-button
            >
          </div>
        </div>
      </el-form>
      <p v-if="error" class="eval-dialog-error">{{ error }}</p>
      <template #footer
        ><el-button @click="editorOpen = false">关闭</el-button
        ><el-button type="primary" :loading="busy" @click="saveDataset"
          >保存新版本</el-button
        ></template
      >
    </el-dialog>

    <el-dialog
      v-model="createOpen"
      title="创建批量评测任务"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="任务名称"
          ><el-input v-model="createForm.name" maxlength="128"
        /></el-form-item>
        <el-form-item label="评测集"
          ><el-select
            v-model="createForm.dataset_id"
            :disabled="!!createForm.parent_run_id"
            filterable
            ><el-option
              v-for="dataset in datasets"
              :key="dataset.id"
              :label="`${dataset.name} · ${dataset.case_count} 条 · ${dateLabel(dataset.created_at)}`"
              :value="dataset.id" /></el-select
        ></el-form-item>
        <p v-if="createForm.parent_run_id" class="muted">
          复测原任务中的
          {{ createCaseCount }} 个用例；原结果不会被覆盖，可重新选择配置和模型。
        </p>
        <el-form-item label="业务配置"
          ><el-select v-model="createForm.release_id"
            ><el-option label="创建时当前生效配置" :value="0" /><el-option
              v-for="release in releases"
              :key="release.id"
              :label="`${release.note || '业务配置'} · ${dateLabel(release.created_at)}`"
              :value="release.id" /></el-select
        ></el-form-item>
        <div class="eval-form-grid">
          <el-form-item label="识别模型"
            ><el-select v-model="createForm.model_uid"
              ><el-option
                v-for="model in models.filter((item) => item.enabled)"
                :key="model.model_uid"
                :label="model.display_name"
                :value="model.model_uid" /></el-select
          ></el-form-item>
          <el-form-item label="评审模型"
            ><el-select
              v-model="createForm.judge_model_uid"
              clearable
              placeholder="不选则人工复核"
              ><el-option
                v-for="model in models.filter((item) => item.enabled)"
                :key="model.model_uid"
                :label="model.display_name"
                :value="model.model_uid" /></el-select
          ></el-form-item>
          <el-form-item label="每条重复次数"
            ><el-select v-model="createForm.repeat_count"
              ><el-option
                v-for="count in [1, 3, 5]"
                :key="count"
                :label="`${count} 次`"
                :value="count" /></el-select
          ></el-form-item>
          <el-form-item label="并发数"
            ><el-input-number
              v-model="createForm.worker_concurrency"
              :min="1"
              :max="8"
          /></el-form-item>
          <el-form-item label="验收目标通过率（%）"
            ><el-input-number
              v-model="createForm.pass_threshold"
              :min="0"
              :max="100"
              :precision="2"
          /></el-form-item>
        </div>
        <el-alert
          :title="`${createCaseCount} 条用例 × ${createForm.repeat_count} 次 = ${createCaseCount * createForm.repeat_count} 次识别${createForm.judge_model_uid ? '，另有最多同等次数的模型评审' : '；识别完成后需人工复核标准答案'}。创建后后台将调用所选模型。`"
          type="info"
          :closable="false"
        />
      </el-form>
      <p v-if="error" class="eval-dialog-error">{{ error }}</p>
      <template #footer
        ><el-button @click="createOpen = false">取消</el-button
        ><el-button type="primary" :loading="busy" @click="submitRun"
          >创建并开始评测</el-button
        ></template
      >
    </el-dialog>

    <el-drawer
      :model-value="!!selectedResult"
      title="结果对照与复核"
      size="min(1000px, 96vw)"
      @close="selectedResult = null"
    >
      <template v-if="selectedResult">
        <h2>{{ selectedResult.question }}</h2>
        <p>
          <el-tag :type="statusType(selectedResult.status)">{{
            labels[selectedResult.status]
          }}</el-tag>
          · {{ selectedResult.case_id }} · 第
          {{ selectedResult.repeat_index + 1 }} 次
        </p>
        <div class="eval-result-comparison">
          <article>
            <h3>标准答案</h3>
            <p class="eval-preserve">{{ selectedResult.standard_answer }}</p>
            <p v-if="selectedResult.expected?.composition">
              期望组合：{{
                {
                  single: "单动作",
                  parallel: "并行",
                  sequential: "顺序",
                  alternative: "备选",
                }[selectedResult.expected.composition]
              }}
            </p>
            <p v-if="selectedResult.expected?.need_clarification != null">
              期望追问：{{
                selectedResult.expected.need_clarification
                  ? "必须追问"
                  : "不得追问"
              }}
            </p>
            <p
              v-if="
                selectedResult.expected && 'risk' in selectedResult.expected
              "
            >
              期望风险：{{
                selectedResult.expected.risk
                  ? `${selectedResult.expected.risk.type}（${selectedResult.expected.risk.level}）`
                  : "无风险"
              }}
            </p>
            <div v-if="selectedResult.expected?.actions?.length">
              <h4>精确动作要求</h4>
              <div
                v-for="(action, index) in selectedResult.expected.actions"
                :key="index"
                class="eval-action-card"
              >
                <strong>动作 {{ index + 1 }}</strong>
                <p>
                  {{ action.route
                  }}<span v-if="'intent' in action">
                    / {{ action.intent ?? "无意图" }}</span
                  >
                </p>
                <p
                  v-for="slot in action.slots ?? []"
                  :key="`${slot.name}:${slot.value}`"
                >
                  {{ slot.name }}：{{ slot.value }}
                </p>
                <p v-if="action.depends_on != null">
                  依赖：{{ action.depends_on.join("、") || "无" }}
                </p>
              </div>
            </div>
          </article>
          <article>
            <h3>实际结果</h3>
            <EvaluationResultView :result="selectedResult.actual" />
          </article>
        </div>
        <h3>判定依据</h3>
        <p class="eval-preserve">{{ selectedResult.reason }}</p>
        <ul v-if="selectedResult.verdict.rules?.issues.length">
          <li
            v-for="issue in selectedResult.verdict.rules.issues"
            :key="issue.field"
          >
            {{ issue.message }}
          </li>
        </ul>
        <p v-if="selectedResult.verdict.judge">
          模型原始评审：{{ labels[selectedResult.verdict.judge.verdict] }} ·
          {{ selectedResult.verdict.judge.reason }}
        </p>
        <el-button
          v-if="selectedResult.trace_state === 'available'"
          @click="inspectTrace"
          >查看调用记录 / Prompt</el-button
        ><span v-else class="muted">{{
          selectedResult.trace_state === "expired"
            ? "Trace 已过期，评测结果仍完整保留"
            : "暂无可用调用记录"
        }}</span>
        <section v-if="canReview" class="eval-review">
          <h3>人工复核</h3>
          <p class="muted">
            修正模型评审结论需要填写理由。记录保留，通过率会按最终结论更新。
          </p>
          <el-input
            v-model="reviewer"
            placeholder="复核人"
            maxlength="128"
          /><el-input
            v-model="reviewReason"
            type="textarea"
            :rows="3"
            placeholder="具体依据；若标准答案有误，请编辑评测集新版本后复测"
            maxlength="2000"
            @input="reviewDirty = true"
          /><el-button type="success" :loading="busy" @click="review('pass')"
            >确认通过</el-button
          ><el-button type="danger" :loading="busy" @click="review('fail')"
            >确认不通过</el-button
          >
        </section>
        <p
          v-else-if="selectedResult.verdict.rules?.issues.length"
          class="muted"
        >
          精确规则不符合不能被人工覆盖。标准有误时请创建评测集新版本。
        </p>
        <p v-if="error" class="eval-dialog-error">{{ error }}</p>
        <section v-if="selectedResult.reviews.length">
          <h3>复核历史</h3>
          <article
            v-for="(entry, index) in selectedResult.reviews"
            :key="index"
          >
            <strong>{{ entry.reviewer }} · {{ labels[entry.decision] }}</strong>
            <p>{{ entry.reason }}</p>
            <small>{{ dateLabel(entry.created_at) }}</small>
          </article>
        </section>
      </template>
    </el-drawer>

    <el-dialog v-model="traceOpen" title="调用诊断" width="min(1000px, 96vw)">
      <pre class="eval-trace">{{ JSON.stringify(traceData, null, 2) }}</pre>
    </el-dialog>
    <el-dialog
      v-model="compareOpen"
      title="对比评测任务"
      width="min(1100px, 96vw)"
    >
      <div class="eval-toolbar">
        <el-select v-model="compareLeft" placeholder="基线任务"
          ><el-option
            v-for="run in runs"
            :key="run.id"
            :value="run.id"
            :label="run.name" /></el-select
        ><el-select v-model="compareRight" placeholder="对比任务"
          ><el-option
            v-for="run in runs"
            :key="run.id"
            :value="run.id"
            :label="run.name" /></el-select
        ><el-button type="primary" :loading="busy" @click="compare"
          >比较</el-button
        >
      </div>
      <p class="muted">
        只允许相同用例与标准答案的任务直接对比。复测子集不能代替完整评测集的通过率。
      </p>
      <p v-if="error" class="eval-dialog-error">{{ error }}</p>
      <template v-if="comparison"
        ><el-alert
          v-if="comparison.warning"
          :title="comparison.warning"
          type="warning"
          :closable="false"
        />
        <div class="eval-compare-rates">
          <div>
            {{ comparison.left.name
            }}<strong>{{ comparison.left.summary.pass_rate }}%</strong
            ><small>{{
              comparison.left.summary.final
                ? "最终通过率"
                : "当前通过率，验收未完成"
            }}</small>
          </div>
          <span>→</span>
          <div>
            {{ comparison.right.name
            }}<strong>{{ comparison.right.summary.pass_rate }}%</strong
            ><small>{{
              comparison.right.summary.final
                ? "最终通过率"
                : "当前通过率，验收未完成"
            }}</small>
          </div>
        </div>
        <el-radio-group v-model="changeFilter"
          ><el-radio-button label="全部" value="" /><el-radio-button
            label="退步"
            value="regression" /><el-radio-button
            label="改善"
            value="improvement" /><el-radio-button
            label="未变化"
            value="unchanged" /><el-radio-button label="待定" value="pending"
        /></el-radio-group>
        <el-table :data="compareRows" max-height="500"
          ><el-table-column
            prop="question"
            label="问题"
            min-width="200" /><el-table-column label="基线" width="110"
            ><template #default="{ row }">{{
              labels[row.before]
            }}</template></el-table-column
          ><el-table-column label="对比" width="110"
            ><template #default="{ row }">{{
              labels[row.after]
            }}</template></el-table-column
          ><el-table-column
            prop="right_reason"
            label="对比任务判定依据"
            min-width="240"
        /></el-table>
      </template>
    </el-dialog>
  </section>
</template>
