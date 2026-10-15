<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { analyzeIntent, IntentApiError, type IntentResult } from "./intentApi";
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

function readableError(value: unknown): string {
  if (!(value instanceof IntentApiError)) {
    return value instanceof Error ? value.message : "识别失败，请稍后重试";
  }
  const messages: Record<string, string> = {
    CONFIG_NOT_READY: "当前运行配置尚未准备好，请检查默认模型和业务配置。",
    INVALID_INPUT: "输入内容或所选模型无效，请检查后重试。",
    SERVICE_BUSY: "模型服务当前繁忙，请稍后重试。",
    MODEL_TIMEOUT: "模型服务响应超时，请重试或检查模型超时设置。",
    MODEL_RATE_LIMIT: "模型服务请求过于频繁，请稍后重试。",
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
  recognizing.value = true;
  error.value = "";
  result.value = null;
  elapsedMs.value = null;
  resultModelLabel.value = "";
  const started = performance.now();
  try {
    resultModelLabel.value = selectedModel.value
      ? `${selectedModel.value.display_name} · ${selectedModel.value.model_name}`
      : "";
    result.value = await analyzeIntent({
      text: text.value,
      context: {},
      model_uid: selectedModelUid.value,
    });
    elapsedMs.value = Math.round(performance.now() - started);
  } catch (value) {
    error.value = readableError(value);
  } finally {
    recognizing.value = false;
  }
}

function confidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

onMounted(() => void loadModels());
</script>

<template>
  <section class="intent-recognition">
    <div class="intent-intro">
      <p>输入一句自然语言，使用已配置的模型识别一级路由、意图和参数。</p>
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
          <el-tag v-if="result" type="success" effect="plain">识别完成</el-tag>
        </div>

        <div v-if="recognizing" class="result-state">
          <span class="intent-spinner" aria-hidden="true"></span>
          <strong>正在识别...</strong>
          <span>模型正在分析 Route、Intent 和 Slot</span>
        </div>

        <div v-else-if="!result" class="result-state empty-result">
          <span class="result-placeholder">R</span>
          <strong>等待识别</strong>
          <span>完成识别后，结果会显示在这里</span>
        </div>

        <div v-else class="result-content">
          <section class="result-section route-section">
            <h3>一级路由</h3>
            <div class="route-value">
              <strong>{{ routeLabels[result.route] ?? result.route }}</strong>
              <code>{{ result.route }}</code>
            </div>
          </section>

          <section class="result-section">
            <h3>意图</h3>
            <div v-if="result.intents.length" class="intent-list">
              <div
                v-for="candidate in result.intents"
                :key="candidate.name"
                class="intent-candidate"
              >
                <div class="candidate-label">
                  <span
                    ><strong>{{ candidate.zh }}</strong
                    ><small>{{ candidate.name }}</small></span
                  >
                  <b>{{ confidence(candidate.confidence) }}</b>
                </div>
                <el-progress
                  :percentage="Math.round(candidate.confidence * 100)"
                  :stroke-width="5"
                  :show-text="false"
                />
              </div>
            </div>
            <p v-else class="empty-value">未识别到二级意图</p>
          </section>

          <section class="result-section">
            <h3>识别参数</h3>
            <dl v-if="result.slots.length" class="slot-list">
              <div
                v-for="(slot, index) in result.slots"
                :key="`${slot.name}-${index}`"
              >
                <dt>
                  {{ slot.zh }} <small>{{ slot.name }}</small>
                </dt>
                <dd>{{ slot.value }}</dd>
              </div>
            </dl>
            <p v-else class="empty-value">未识别到参数</p>
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

          <section
            v-if="result.need_clarification"
            class="result-section clarification"
          >
            <h3>需要补充信息</h3>
            <p>{{ result.clarification }}</p>
          </section>
        </div>
      </section>
    </div>
  </section>
</template>
