<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";

import {
  analyzeIntent,
  getIntentLatencyAnalysis,
  getIntentModelOutput,
  getIntentPrompt,
  IntentApiError,
  type IntentLatencyAnalysis,
  type IntentResult,
} from "./intentApi";
import { modelApi, type ManagedModel } from "./modelApi";

const props = withDefaults(defineProps<{ batch?: boolean }>(), {
  batch: false,
});

const emit = defineEmits<{
  navigate: [path: "/models" | "/config/routes"];
}>();

const routeLabels: Record<string, string> = {
  training_business: "训练业务",
  information_query: "信息查询",
  sports_knowledge: "运动知识",
  safety: "安全相关",
  dialogue_device_control: "对话与设备控制",
  social_chat: "社交闲聊",
  unknown: "暂未识别",
};

const riskLabels: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
};

const compositionLabels: Record<IntentResult["composition"], string> = {
  single: "单一动作",
  parallel: "并行动作",
  sequential: "顺序动作",
  alternative: "候选动作",
};

const text = ref("");
const models = ref<ManagedModel[]>([]);
const defaultModelUid = ref<string | null>(null);
const selectedModelUid = ref("");
const loadingModels = ref(false);
const recognizing = ref(false);
const error = ref("");
const result = ref<IntentResult | null>(null);
const elapsedMs = ref<number | null>(null);
const resultModelLabel = ref("");
const resultModelUid = ref("");
const latencyAnalysis = ref<IntentLatencyAnalysis | null>(null);
const latencyAnalysisLoading = ref(false);
const latencyAnalysisError = ref("");
const jsonCopied = ref(false);
const modelOutputText = ref("");
const modelOutputLoading = ref(false);
const modelOutputError = ref("");
let recognitionVersion = 0;
const promptDialogVisible = ref(false);
const promptLoading = ref(false);
const promptError = ref("");
const promptText = ref("");
const promptTruncated = ref(false);
const promptCopied = ref(false);

type BatchRun = {
  id: number;
  line: number;
  repetition: number;
  text: string;
  modelUid: string;
  modelLabel: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  result: IntentResult | null;
  elapsedMs: number | null;
  error: string;
};

const repeat = ref<1 | 3 | 5>(1);
const batchRuns = ref<BatchRun[]>([]);
const selectedRunId = ref<number | null>(null);
const stopRequested = ref(false);
let disposed = false;
const batchLines = computed(() =>
  text.value
    .split(/\r\n|\n|\r/)
    .map((value, index) => ({
      text: value.trim(),
      line: index + 1,
    }))
    .filter((item) => item.text),
);
const batchInputError = computed(() => {
  const tooLong = batchLines.value.find((item) => [...item.text].length > 2000);
  if (tooLong) return `第 ${tooLong.line} 行超过 2000 字，请缩短后再调试。`;
  if (batchLines.value.length * repeat.value > 100) {
    return "每批最多执行 100 次，请减少输入条数或重复次数。";
  }
  return "";
});
const batchSuccess = computed(
  () => batchRuns.value.filter((run) => run.status === "success").length,
);
const batchFailed = computed(
  () => batchRuns.value.filter((run) => run.status === "failed").length,
);
const batchCancelled = computed(
  () => batchRuns.value.filter((run) => run.status === "cancelled").length,
);
const batchCompleted = computed(() => batchSuccess.value + batchFailed.value);
const selectedRun = computed(() =>
  batchRuns.value.find((run) => run.id === selectedRunId.value),
);
const runStatusLabels: Record<BatchRun["status"], string> = {
  queued: "等待中",
  running: "识别中",
  success: "成功",
  failed: "失败",
  cancelled: "已停止",
};

function batchRowClass({ row }: { row: BatchRun }): string {
  return row.id === selectedRunId.value ? "selected-batch-row" : "";
}

function runStatusLabel(run: BatchRun): string {
  return runStatusLabels[run.status];
}

const enabledModels = computed(() =>
  models.value.filter((model) => model.enabled),
);
const selectedModel = computed(() =>
  enabledModels.value.find(
    (model) => model.model_uid === selectedModelUid.value,
  ),
);
const canSubmit = computed(
  () =>
    Boolean(text.value.trim() && selectedModel.value) &&
    !recognizing.value &&
    !loadingModels.value &&
    (!props.batch || !batchInputError.value),
);
const providerLatencyMs = computed(
  () => latencyAnalysis.value?.current.provider_latency_ms ?? null,
);
const applicationLatencyMs = computed(() => {
  if (elapsedMs.value === null || providerLatencyMs.value === null) return null;
  return Math.max(0, elapsedMs.value - providerLatencyMs.value);
});
const providerLatencyRatio = computed(() => {
  if (!elapsedMs.value || providerLatencyMs.value === null) return 0;
  return Math.min(
    100,
    Math.round((providerLatencyMs.value / elapsedMs.value) * 100),
  );
});
const latencyVerdict = computed(() => {
  const current = providerLatencyMs.value ?? elapsedMs.value;
  const baseline = latencyAnalysis.value?.baseline;
  if (current === null) {
    return { label: "暂无数据", type: "info" as const, detail: "" };
  }
  if (
    baseline &&
    baseline.p50_ms !== null &&
    baseline.p95_ms !== null &&
    baseline.sample_size
  ) {
    if (current <= baseline.p50_ms) {
      return {
        label: "较快",
        type: "success" as const,
        detail: `快于该模型近期中位数 ${formatDuration(baseline.p50_ms)}`,
      };
    }
    if (current <= baseline.p95_ms) {
      return {
        label: "正常波动",
        type: "info" as const,
        detail: `处于近期 P50～P95 区间（${baseline.sample_size} 个样本）`,
      };
    }
    return {
      label: "偏慢",
      type: "warning" as const,
      detail: `超过该模型近期 P95 ${formatDuration(baseline.p95_ms)}`,
    };
  }
  if (current <= 3000) {
    return {
      label: "较快",
      type: "success" as const,
      detail: "本次耗时不超过 3 秒",
    };
  }
  if (current <= 10000) {
    return {
      label: "正常",
      type: "info" as const,
      detail: "暂无足够历史样本用于对比",
    };
  }
  return {
    label: "偏慢",
    type: "warning" as const,
    detail: "暂无足够历史样本用于对比",
  };
});
const resultJson = computed(() => {
  if (!modelOutputText.value) return "";
  try {
    return JSON.stringify(JSON.parse(modelOutputText.value), null, 2);
  } catch {
    return modelOutputText.value;
  }
});

function readableError(value: unknown): string {
  if (!(value instanceof IntentApiError)) {
    return value instanceof Error ? value.message : "识别失败，请稍后重试";
  }
  if (
    value.code === "MODEL_OUTPUT_SCHEMA_ERROR" &&
    value.message.startsWith("模型返回字段不符合要求")
  ) {
    return value.message;
  }
  const messages: Record<string, string> = {
    CONFIG_NOT_READY: "当前运行配置尚未准备好，请检查默认模型和业务配置。",
    INVALID_INPUT: "输入内容或所选模型无效，请检查后重试。",
    SERVICE_BUSY: "模型服务当前繁忙，请稍后重试。",
    MODEL_TIMEOUT: "模型服务响应超时，请重试或检查模型超时设置。",
    MODEL_RATE_LIMIT: "模型服务请求过于频繁，请稍后重试。",
    MODEL_AUTH_FAILED: "模型服务认证失败，请检查 API Key。",
    MODEL_NOT_FOUND: "模型名称不存在或当前 API Key 无权调用，请重新配置模型。",
    MODEL_PROVIDER_ERROR:
      "模型服务调用失败，请检查 API 地址、API Key 和模型名称。",
    MODEL_OUTPUT_PARSE_ERROR: "模型没有返回可解析的识别结果，请重新识别。",
    MODEL_OUTPUT_SCHEMA_ERROR: "模型返回结果不符合意图识别格式，请重新识别。",
    INTERNAL_ERROR: "系统处理失败，请稍后重试。",
  };
  return messages[value.code] ?? value.message;
}

async function loadModels() {
  loadingModels.value = true;
  error.value = "";
  try {
    const response = await modelApi.list();
    models.value = response.items;
    defaultModelUid.value = response.default_model_uid;
    const available = response.items.filter((model) => model.enabled);
    const currentStillAvailable = available.some(
      (model) => model.model_uid === selectedModelUid.value,
    );
    if (!currentStillAvailable) {
      selectedModelUid.value =
        available.find(
          (model) => model.model_uid === response.default_model_uid,
        )?.model_uid ??
        available[0]?.model_uid ??
        "";
    }
  } catch (value) {
    error.value =
      value instanceof Error ? value.message : "无法加载模型列表，请稍后重试";
  } finally {
    loadingModels.value = false;
  }
}

function resetResult() {
  ++recognitionVersion;
  result.value = null;
  elapsedMs.value = null;
  resultModelLabel.value = "";
  resultModelUid.value = "";
  latencyAnalysis.value = null;
  latencyAnalysisError.value = "";
  latencyAnalysisLoading.value = false;
  jsonCopied.value = false;
  modelOutputText.value = "";
  modelOutputLoading.value = false;
  modelOutputError.value = "";
  promptDialogVisible.value = false;
  promptLoading.value = false;
  promptError.value = "";
  promptText.value = "";
  promptTruncated.value = false;
  promptCopied.value = false;
}

async function selectRun(run: BatchRun) {
  if (!run.result || disposed) return;
  resetResult();
  selectedRunId.value = run.id;
  result.value = run.result;
  elapsedMs.value = run.elapsedMs;
  resultModelUid.value = run.modelUid;
  resultModelLabel.value = run.modelLabel;
  await Promise.all([loadLatencyAnalysis(), loadModelOutput()]);
}

async function executeBatch(queue: BatchRun[]) {
  if (recognizing.value || !queue.length || disposed) return;
  recognizing.value = true;
  stopRequested.value = false;
  error.value = "";
  for (const run of queue) {
    run.status = "queued";
    run.error = "";
    run.elapsedMs = null;
    run.result = null;
  }
  try {
    for (const run of queue) {
      if (stopRequested.value || disposed) break;
      run.status = "running";
      const started = performance.now();
      try {
        run.result = await analyzeIntent({
          text: run.text,
          context: {},
          model_uid: run.modelUid,
        });
        run.status = "success";
      } catch (value) {
        run.error = readableError(value);
        run.status = "failed";
      } finally {
        run.elapsedMs = Math.round(performance.now() - started);
      }
      if (run.result && selectedRunId.value === null && !disposed) {
        void selectRun(run);
      }
    }
  } finally {
    for (const run of queue) {
      if (run.status === "queued") run.status = "cancelled";
    }
    recognizing.value = false;
  }
}

async function startBatch() {
  if (!canSubmit.value || !selectedModel.value) return;
  resetResult();
  selectedRunId.value = null;
  const model = selectedModel.value;
  batchRuns.value = batchLines.value.flatMap((item, index) =>
    Array.from({ length: repeat.value }, (_, repetition): BatchRun => ({
      id: index * repeat.value + repetition + 1,
      line: item.line,
      repetition: repetition + 1,
      text: item.text,
      modelUid: model.model_uid,
      modelLabel: `${model.display_name} · ${model.model_name}`,
      status: "queued",
      result: null,
      elapsedMs: null,
      error: "",
    })),
  );
  await executeBatch(batchRuns.value);
}

async function retryFailed() {
  await executeBatch(batchRuns.value.filter((run) => run.status === "failed"));
}

async function recognize() {
  if (!canSubmit.value) return;
  if (props.batch) return startBatch();
  resetResult();
  const version = recognitionVersion;
  recognizing.value = true;
  error.value = "";
  const started = performance.now();
  try {
    const modelUid = selectedModelUid.value;
    resultModelUid.value = modelUid;
    resultModelLabel.value = selectedModel.value
      ? `${selectedModel.value.display_name} · ${selectedModel.value.model_name}`
      : "";
    const recognized = await analyzeIntent({
      text: text.value,
      context: {},
      model_uid: modelUid,
    });
    if (disposed || version !== recognitionVersion) return;
    elapsedMs.value = Math.round(performance.now() - started);
    result.value = recognized;
    recognizing.value = false;
    await Promise.all([loadLatencyAnalysis(), loadModelOutput()]);
  } catch (value) {
    if (version === recognitionVersion) error.value = readableError(value);
  } finally {
    if (version === recognitionVersion) recognizing.value = false;
  }
}

async function loadLatencyAnalysis() {
  if (!result.value || !resultModelUid.value) return;
  const version = recognitionVersion;
  latencyAnalysisLoading.value = true;
  try {
    const analysis = await getIntentLatencyAnalysis(
      result.value.request_id,
      resultModelUid.value,
    );
    if (version === recognitionVersion) latencyAnalysis.value = analysis;
  } catch {
    if (version === recognitionVersion) {
      latencyAnalysisError.value = "服务端耗时明细暂不可用，已保留端到端用时。";
    }
  } finally {
    if (version === recognitionVersion) latencyAnalysisLoading.value = false;
  }
}

async function loadModelOutput() {
  if (!result.value || !resultModelUid.value || modelOutputLoading.value)
    return;
  const version = recognitionVersion;
  modelOutputLoading.value = true;
  modelOutputError.value = "";
  try {
    const output = await getIntentModelOutput(
      result.value.request_id,
      resultModelUid.value,
    );
    if (version === recognitionVersion) modelOutputText.value = output.content;
  } catch (value) {
    if (version === recognitionVersion) {
      modelOutputError.value =
        value instanceof Error
          ? value.message
          : "LLM 原始 JSON 加载失败，请重试";
    }
  } finally {
    if (version === recognitionVersion) modelOutputLoading.value = false;
  }
}

function confidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value} ms`;
}

async function copyResultJson() {
  if (!resultJson.value) return;
  try {
    await navigator.clipboard.writeText(resultJson.value);
    jsonCopied.value = true;
    window.setTimeout(() => {
      jsonCopied.value = false;
    }, 1600);
  } catch {
    ElMessage.error("复制失败，请手动选择 JSON 内容");
  }
}

async function openPrompt() {
  if (!result.value || !resultModelUid.value) return;
  const version = recognitionVersion;
  promptDialogVisible.value = true;
  promptCopied.value = false;
  if (promptText.value) return;
  promptLoading.value = true;
  promptError.value = "";
  try {
    const prompt = await getIntentPrompt(
      result.value.request_id,
      resultModelUid.value,
    );
    if (version !== recognitionVersion) return;
    promptText.value = prompt.final_prompt;
    promptTruncated.value = prompt.truncated;
  } catch (value) {
    if (version !== recognitionVersion) return;
    promptError.value =
      value instanceof IntentApiError
        ? value.message
        : value instanceof Error
          ? value.message
          : "提示词加载失败，请稍后重试";
  } finally {
    if (version === recognitionVersion) promptLoading.value = false;
  }
}

async function copyPrompt() {
  if (!promptText.value) return;
  try {
    await navigator.clipboard.writeText(promptText.value);
    promptCopied.value = true;
    window.setTimeout(() => {
      promptCopied.value = false;
    }, 1600);
  } catch {
    ElMessage.error("复制失败，请手动选择提示词内容");
  }
}

onMounted(() => void loadModels());
onBeforeUnmount(() => {
  disposed = true;
  stopRequested.value = true;
  ++recognitionVersion;
});
</script>

<template>
  <section class="intent-recognition" :class="{ 'batch-recognition': batch }">
    <div class="intent-intro">
      <p v-if="batch">
        每行输入一条内容，按顺序独立识别；可重复执行并逐条查看完整结果。离开页面会停止后续任务。
      </p>
      <p v-else>
        输入一句自然语言，识别其中一个或多个可独立处理的动作、路由和参数。
      </p>
    </div>

    <div class="intent-layout">
      <section class="intent-panel intent-compose-panel">
        <div class="panel-heading">
          <div>
            <h2>{{ batch ? "多条调试输入" : "识别输入" }}</h2>
          </div>
        </div>

        <label class="field-label" for="intent-model">使用模型</label>
        <div class="model-select-row">
          <el-select
            id="intent-model"
            v-model="selectedModelUid"
            :loading="loadingModels"
            :disabled="recognizing"
            placeholder="请选择模型"
          >
            <el-option
              v-for="model in enabledModels"
              :key="model.model_uid"
              :value="model.model_uid"
              :label="`${model.display_name} · ${model.model_name}`"
            >
              <div class="model-option">
                <span>{{ model.display_name }} · {{ model.model_name }}</span>
                <small v-if="model.is_default">默认</small>
              </div>
            </el-option>
          </el-select>
          <el-button
            :loading="loadingModels"
            :disabled="recognizing"
            @click="loadModels"
            >刷新</el-button
          >
        </div>

        <div
          v-if="!loadingModels && enabledModels.length === 0"
          class="no-model-notice"
        >
          <span>当前没有可用模型</span>
          <el-button link type="primary" @click="emit('navigate', '/models')">
            前往模型管理
          </el-button>
        </div>

        <label class="field-label" for="intent-text">{{
          batch ? "调试内容（每行一条，空行自动忽略）" : "需要识别的内容"
        }}</label>
        <el-input
          id="intent-text"
          v-model="text"
          type="textarea"
          :rows="7"
          :maxlength="batch ? undefined : 2000"
          :show-word-limit="!batch"
          resize="vertical"
          :disabled="recognizing"
          :placeholder="
            batch
              ? '我想制定一个减脂训练计划\n今天跑了多少公里\n暂停训练'
              : '例如：我想制定一个减脂训练计划'
          "
          @keydown.ctrl.enter="recognize"
        />

        <div v-if="batch" class="batch-options">
          <label class="field-label" id="batch-repeat-label"
            >每条重复次数</label
          >
          <el-radio-group
            v-model="repeat"
            :disabled="recognizing"
            aria-labelledby="batch-repeat-label"
          >
            <el-radio-button :value="1">1 次</el-radio-button>
            <el-radio-button :value="3">3 次</el-radio-button>
            <el-radio-button :value="5">5 次</el-radio-button>
          </el-radio-group>
          <p class="batch-hint">
            {{ batchLines.length }} 条内容，共
            {{ batchLines.length * repeat }} 次调用；每条最多 2000 字，每批最多
            100 次。
          </p>
          <el-alert
            v-if="batchInputError"
            :title="batchInputError"
            type="warning"
            :closable="false"
            show-icon
          />
        </div>

        <div class="submit-row">
          <span>Ctrl + Enter {{ batch ? "开始调试" : "快速识别" }}</span>
          <el-button
            type="primary"
            :loading="recognizing"
            :disabled="!canSubmit"
            @click="recognize"
          >
            {{
              recognizing ? "正在识别..." : batch ? "开始多条调试" : "开始识别"
            }}
          </el-button>
        </div>

        <el-alert
          v-if="error"
          class="intent-error"
          :title="error"
          type="error"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button size="small" :disabled="!canSubmit" @click="recognize"
                >重新识别</el-button
              >
              <el-button size="small" @click="emit('navigate', '/models')">
                检查模型配置
              </el-button>
              <el-button size="small" @click="emit('navigate', '/config/routes')">
                检查业务配置
              </el-button>
            </div>
          </template>
        </el-alert>
      </section>

      <section
        v-if="batch && batchRuns.length"
        class="intent-panel batch-results-panel"
        aria-live="polite"
      >
        <div class="panel-heading">
          <div>
            <h2>调试结果</h2>
            <p>
              已执行 {{ batchCompleted }}/{{ batchRuns.length }} · 成功
              {{ batchSuccess }} · 失败 {{ batchFailed }} · 已停止
              {{ batchCancelled }}
            </p>
          </div>
        </div>
        <el-progress
          :percentage="Math.round((batchCompleted / batchRuns.length) * 100)"
          :status="
            !recognizing && batchSuccess === batchRuns.length
              ? 'success'
              : undefined
          "
        />
        <div class="batch-actions">
          <el-button
            v-if="recognizing"
            :disabled="stopRequested"
            @click="stopRequested = true"
          >
            {{ stopRequested ? "等待当前请求完成…" : "停止后续任务" }}
          </el-button>
          <el-button v-else :disabled="!batchFailed" @click="retryFailed"
            >重试失败项（{{ batchFailed }}）</el-button
          >
          <span class="batch-hint">重试使用各条记录原先选择的模型。</span>
        </div>
        <el-table
          :data="batchRuns"
          row-key="id"
          max-height="520"
          :row-class-name="batchRowClass"
        >
          <el-table-column label="条目" width="80">
            <template #default="{ row }">
              <div>#{{ row.id }}</div>
              <small>行 {{ row.line }} / 第 {{ row.repetition }} 次</small>
            </template>
          </el-table-column>
          <el-table-column label="输入 / 识别结果" min-width="180">
            <template #default="{ row }">
              <div class="batch-input-text">{{ row.text }}</div>
              <p v-if="row.error" class="batch-run-error">{{ row.error }}</p>
              <div
                v-for="action in row.result?.actions ?? []"
                :key="action.action_id"
                class="batch-action-summary"
              >
                {{ routeLabels[action.route] ?? action.route }} ·
                {{ action.intent?.zh ?? "未识别到二级意图" }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态 / 用时" width="100">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="
                  row.status === 'success'
                    ? 'success'
                    : row.status === 'failed'
                      ? 'danger'
                      : 'info'
                "
                >{{ runStatusLabel(row) }}</el-tag
              >
              <div>{{ formatDuration(row.elapsedMs) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="详情" width="85" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :disabled="!row.result"
                @click="selectRun(row)"
                >{{
                  row.id === selectedRunId ? "当前结果" : "查看结果"
                }}</el-button
              >
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="intent-panel intent-result-panel" aria-live="polite">
        <div class="panel-heading">
          <div>
            <h2>
              {{
                batch && selectedRun
                  ? `第 ${selectedRun.line} 行 · 第 ${selectedRun.repetition} 次识别结果`
                  : "识别结果"
              }}
            </h2>
            <p v-if="result">
              {{ resultModelLabel }}
              <span v-if="elapsedMs !== null"> · {{ elapsedMs }} ms</span>
            </p>
          </div>
          <div v-if="result" class="result-heading-actions">
            <el-button size="small" plain @click="openPrompt">
              查看发送提示词
            </el-button>
            <el-tag type="success" effect="plain">识别完成</el-tag>
          </div>
        </div>

        <div v-if="recognizing && !batch" class="result-state">
          <span class="intent-spinner" aria-hidden="true"></span>
          <strong>正在识别...</strong>
          <span>模型正在拆分 Action，并分析 Route、Intent 和 Slot</span>
        </div>

        <div v-else-if="!result" class="result-state empty-result">
          <span class="result-placeholder">R</span>
          <strong>等待识别</strong>
          <span>{{
            batch
              ? "首条成功结果将自动展示，也可在结果列表中选择查看"
              : "完成识别后，结果会显示在这里"
          }}</span>
        </div>

        <div v-else class="result-content">
          <section
            v-if="batch && selectedRun"
            class="result-section batch-selected-input"
          >
            <h3>本次输入</h3>
            <p>{{ selectedRun.text }}</p>
          </section>
          <section class="result-section action-plan-summary">
            <div>
              <h3>动作计划</h3>
              <strong>{{ result.actions.length }} 个动作</strong>
            </div>
            <el-tag effect="plain">
              {{ compositionLabels[result.composition] }}
            </el-tag>
          </section>

          <section class="result-section action-list-section">
            <h3>分动作识别结果（后端处理后）</h3>
            <div class="action-list">
              <article
                v-for="action in result.actions"
                :key="action.action_id"
                class="action-card"
              >
                <header class="action-card-header">
                  <div>
                    <span>动作 {{ action.order }}</span>
                    <code>{{ action.action_id }}</code>
                  </div>
                  <el-tag size="small" effect="plain">
                    {{ routeLabels[action.route] ?? action.route }}
                  </el-tag>
                </header>

                <div class="action-route">
                  <span>Route</span>
                  <code>{{ action.route }}</code>
                </div>

                <div v-if="action.intent" class="intent-candidate">
                  <div class="candidate-label">
                    <span>
                      <strong>{{ action.intent.zh }}</strong>
                      <small>{{ action.intent.name }}</small>
                    </span>
                    <b>{{ confidence(action.intent.confidence) }}</b>
                  </div>
                  <el-progress
                    :percentage="Math.round(action.intent.confidence * 100)"
                    :stroke-width="5"
                    :show-text="false"
                  />
                </div>
                <p v-else class="empty-value">该动作未识别到二级意图</p>

                <div class="action-slots">
                  <h4>参数</h4>
                  <dl v-if="action.slots.length" class="slot-list">
                    <div
                      v-for="(slot, index) in action.slots"
                      :key="`${action.action_id}-${slot.name}-${index}`"
                    >
                      <dt>
                        {{ slot.zh }} <small>{{ slot.name }}</small>
                      </dt>
                      <dd>{{ slot.value }}</dd>
                    </div>
                  </dl>
                  <p v-else class="empty-value">无参数</p>
                </div>

                <div
                  v-if="action.depends_on.length"
                  class="action-dependencies"
                >
                  <span>依赖动作</span>
                  <code
                    v-for="dependency in action.depends_on"
                    :key="dependency"
                  >
                    {{ dependency }}
                  </code>
                </div>
              </article>
            </div>
          </section>

          <section class="result-section compact-result-row">
            <div>
              <h3>风险</h3>
              <el-tag v-if="!result.risk" type="success" effect="light"
                >无</el-tag
              >
              <div v-else class="risk-value">
                <el-tag
                  :type="
                    result.risk.level === 'high'
                      ? 'danger'
                      : result.risk.level === 'medium'
                        ? 'warning'
                        : 'info'
                  "
                >
                  {{ riskLabels[result.risk.level] }}风险
                </el-tag>
                <span>{{ result.risk.zh }}</span>
              </div>
            </div>
          </section>

          <section class="result-section latency-analysis-section">
            <div class="latency-title-row">
              <h3>识别用时分析</h3>
              <el-tag :type="latencyVerdict.type" size="small" effect="plain">
                {{ latencyVerdict.label }}
              </el-tag>
            </div>

            <div class="latency-metrics">
              <div>
                <span>端到端用时</span>
                <strong>{{ formatDuration(elapsedMs) }}</strong>
                <small>浏览器发起请求至收到结果</small>
              </div>
              <div>
                <span>模型调用</span>
                <strong>{{ formatDuration(providerLatencyMs) }}</strong>
                <small>服务端模型请求累计耗时</small>
              </div>
              <div>
                <span>应用与网络</span>
                <strong>{{ formatDuration(applicationLatencyMs) }}</strong>
                <small>传输、配置、校验及持久化</small>
              </div>
              <div>
                <span>近期平均</span>
                <strong>{{
                  formatDuration(latencyAnalysis?.baseline.average_ms ?? null)
                }}</strong>
                <small>
                  同模型最近
                  {{ latencyAnalysis?.baseline.sample_size ?? 0 }} 个成功样本
                </small>
              </div>
            </div>

            <div v-if="latencyAnalysisLoading" class="latency-loading">
              正在读取服务端耗时明细…
            </div>
            <template v-else>
              <div
                v-if="providerLatencyMs !== null && elapsedMs !== null"
                class="latency-breakdown"
              >
                <div class="latency-breakdown-labels">
                  <span>模型调用 {{ providerLatencyRatio }}%</span>
                  <span>应用与网络 {{ 100 - providerLatencyRatio }}%</span>
                </div>
                <div class="latency-bar" aria-label="识别耗时构成">
                  <span :style="{ width: `${providerLatencyRatio}%` }"></span>
                </div>
              </div>
              <p class="latency-verdict-detail">{{ latencyVerdict.detail }}</p>
              <div v-if="latencyAnalysis" class="latency-meta">
                <span>调用 {{ latencyAnalysis.current.attempt_count }} 次</span>
                <span>重试 {{ latencyAnalysis.current.retry_count }} 次</span>
                <span>
                  Token {{ latencyAnalysis.current.total_tokens ?? "—" }}
                </span>
                <span>
                  P95 {{ formatDuration(latencyAnalysis.baseline.p95_ms) }}
                </span>
              </div>
              <p v-if="latencyAnalysisError" class="latency-analysis-error">
                {{ latencyAnalysisError }}
              </p>
            </template>
          </section>

          <section
            v-if="result.need_clarification"
            class="result-section clarification"
          >
            <h3>需要补充信息（后端处理后）</h3>
            <p>{{ result.clarification }}</p>
          </section>

          <section class="result-section json-output-section">
            <div class="json-output-heading">
              <div>
                <h3>LLM 原始 JSON</h3>
                <p>
                  本次模型生成的原始内容，仅格式化缩进；调用记录中的敏感内容已脱敏。
                </p>
              </div>
              <el-button
                size="small"
                plain
                :disabled="!resultJson || modelOutputLoading"
                @click="copyResultJson"
              >
                {{ jsonCopied ? "已复制" : "复制 JSON" }}
              </el-button>
            </div>
            <p v-if="modelOutputLoading" class="empty-value">
              正在读取 LLM 原始 JSON…
            </p>
            <div v-else-if="modelOutputError">
              <el-alert
                :title="modelOutputError"
                type="error"
                show-icon
                :closable="false"
              />
              <el-button size="small" plain @click="loadModelOutput">
                重新读取
              </el-button>
            </div>
            <pre v-else><code>{{ resultJson }}</code></pre>
          </section>
        </div>
      </section>
    </div>

    <el-dialog
      v-model="promptDialogVisible"
      title="本次发送提示词"
      width="min(920px, 92vw)"
      class="intent-prompt-dialog"
    >
      <p class="prompt-dialog-description">
        来自本次模型调用记录，按实际发送顺序展示；敏感内容会自动脱敏。
      </p>
      <div v-if="promptLoading" class="prompt-dialog-state">
        正在读取提示词…
      </div>
      <el-alert
        v-else-if="promptError"
        :title="promptError"
        type="error"
        show-icon
        :closable="false"
      />
      <template v-else>
        <el-alert
          v-if="promptTruncated"
          title="提示词超过调用记录保存上限，以下内容已截断。"
          type="warning"
          show-icon
          :closable="false"
        />
        <pre class="intent-prompt-content">{{ promptText }}</pre>
      </template>
      <template #footer>
        <el-button @click="promptDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!promptText" @click="copyPrompt">
          {{ promptCopied ? "已复制" : "复制提示词" }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
