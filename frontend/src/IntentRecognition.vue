<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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

const emit = defineEmits<{
  navigate: [path: "/models" | "/config"];
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
    Boolean(text.value.trim() && selectedModelUid.value) && !recognizing.value,
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
  return Math.min(100, Math.round((providerLatencyMs.value / elapsedMs.value) * 100));
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
    return { label: "较快", type: "success" as const, detail: "本次耗时不超过 3 秒" };
  }
  if (current <= 10000) {
    return { label: "正常", type: "info" as const, detail: "暂无足够历史样本用于对比" };
  }
  return { label: "偏慢", type: "warning" as const, detail: "暂无足够历史样本用于对比" };
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

async function recognize() {
  if (!canSubmit.value) return;
  const version = ++recognitionVersion;
  recognizing.value = true;
  error.value = "";
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
  if (!result.value || !resultModelUid.value || modelOutputLoading.value) return;
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
        value instanceof Error ? value.message : "LLM 原始 JSON 加载失败，请重试";
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
    promptText.value = prompt.final_prompt;
    promptTruncated.value = prompt.truncated;
  } catch (value) {
    promptError.value =
      value instanceof IntentApiError
        ? value.message
        : value instanceof Error
          ? value.message
          : "提示词加载失败，请稍后重试";
  } finally {
    promptLoading.value = false;
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
</script>

<template>
  <section class="intent-recognition">
    <div class="intent-intro">
      <p>输入一句自然语言，识别其中一个或多个可独立处理的动作、路由和参数。</p>
    </div>

    <div class="intent-layout">
      <section class="intent-panel intent-compose-panel">
        <div class="panel-heading">
          <div>
            <h2>识别输入</h2>
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
          <el-button :loading="loadingModels" @click="loadModels"
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

        <label class="field-label" for="intent-text">需要识别的内容</label>
        <el-input
          id="intent-text"
          v-model="text"
          type="textarea"
          :rows="7"
          maxlength="2000"
          show-word-limit
          resize="vertical"
          :disabled="recognizing"
          placeholder="例如：我想制定一个减脂训练计划"
          @keydown.ctrl.enter="recognize"
        />

        <div class="submit-row">
          <span>Ctrl + Enter 快速识别</span>
          <el-button
            type="primary"
            :loading="recognizing"
            :disabled="!canSubmit"
            @click="recognize"
          >
            {{ recognizing ? "正在识别..." : "开始识别" }}
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
              <el-button size="small" @click="recognize">重新识别</el-button>
              <el-button size="small" @click="emit('navigate', '/models')">
                检查模型配置
              </el-button>
              <el-button size="small" @click="emit('navigate', '/config')">
                检查业务配置
              </el-button>
            </div>
          </template>
        </el-alert>
      </section>

      <section class="intent-panel intent-result-panel" aria-live="polite">
        <div class="panel-heading">
          <div>
            <h2>识别结果</h2>
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

        <div v-if="recognizing" class="result-state">
          <span class="intent-spinner" aria-hidden="true"></span>
          <strong>正在识别...</strong>
          <span>模型正在拆分 Action，并分析 Route、Intent 和 Slot</span>
        </div>

        <div v-else-if="!result" class="result-state empty-result">
          <span class="result-placeholder">R</span>
          <strong>等待识别</strong>
          <span>完成识别后，结果会显示在这里</span>
        </div>

        <div v-else class="result-content">
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
                      <dt>{{ slot.zh }} <small>{{ slot.name }}</small></dt>
                      <dd>{{ slot.value }}</dd>
                    </div>
                  </dl>
                  <p v-else class="empty-value">无参数</p>
                </div>

                <div v-if="action.depends_on.length" class="action-dependencies">
                  <span>依赖动作</span>
                  <code v-for="dependency in action.depends_on" :key="dependency">
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
                <strong>{{ formatDuration(latencyAnalysis?.baseline.average_ms ?? null) }}</strong>
                <small>
                  同模型最近 {{ latencyAnalysis?.baseline.sample_size ?? 0 }} 个成功样本
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
                <p>本次模型生成的原始内容，仅格式化缩进；调用记录中的敏感内容已脱敏。</p>
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
        <el-button
          type="primary"
          :disabled="!promptText"
          @click="copyPrompt"
        >
          {{ promptCopied ? "已复制" : "复制提示词" }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
