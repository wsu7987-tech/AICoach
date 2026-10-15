<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import {
  modelApi,
  type ManagedModel,
  type ModelCreateInput,
  type ModelServiceTestResult,
  type ModelUpdateInput,
} from "./modelApi";

type DialogMode = "create" | "edit" | "copy";

const loading = ref(false);
const saving = ref(false);
const verifying = ref(false);
const error = ref("");
const models = ref<ManagedModel[]>([]);
const dialogVisible = ref(false);
const mode = ref<DialogMode>("create");
const editing = ref<ManagedModel | null>(null);
const showAdvanced = ref(false);
const replaceCredential = ref(false);
const verified = ref(false);
const verifyMessage = ref("");
const verifyError = ref("");
const availableModels = ref<string[]>([]);
const serviceTestVisible = ref(false);
const serviceTesting = ref(false);
const serviceTestModel = ref<ManagedModel | null>(null);
const serviceTestError = ref("");
const serviceTestResult = ref<ModelServiceTestResult | null>(null);
const serviceTestElapsedMs = ref<number | null>(null);

const serviceTestForm = reactive({
  system_prompt:
    "你是意图识别助手。请根据用户问句，只返回最匹配的意图名称，不要补充解释。",
  question: "",
  reference_intent: "",
});

const form = reactive<ModelCreateInput>({
  display_name: "",
  base_url: "",
  api_key: "",
  model_name: "",
  temperature: 0.1,
  top_p: 0.8,
  timeout_seconds: 30,
  max_retries: 1,
  max_concurrency: 4,
});

const dialogTitle = computed(() => {
  if (mode.value === "edit") return "编辑模型";
  if (mode.value === "copy") return "基于当前模型创建新模型";
  return "添加模型";
});
const identityLocked = computed(() => mode.value === "edit");
const needsNewCredential = computed(
  () => mode.value !== "edit" || replaceCredential.value,
);
const canVerify = computed(() => {
  if (identityLocked.value && !replaceCredential.value) return true;
  return Boolean(form.base_url.trim() && form.api_key.trim());
});
const canSave = computed(() => {
  const basic = Boolean(
    form.display_name.trim() &&
      form.base_url.trim() &&
      form.model_name.trim(),
  );
  if (!basic) return false;
  if (mode.value !== "edit") return Boolean(form.api_key.trim() && verified.value);
  if (replaceCredential.value) return Boolean(form.api_key.trim() && verified.value);
  return true;
});
const canRunServiceTest = computed(
  () =>
    Boolean(
      serviceTestModel.value?.enabled &&
        serviceTestForm.system_prompt.trim() &&
        serviceTestForm.question.trim(),
    ) && !serviceTesting.value,
);
const clientOverheadMs = computed(() => {
  if (serviceTestElapsedMs.value === null || !serviceTestResult.value) {
    return null;
  }
  return Math.max(
    0,
    serviceTestElapsedMs.value - serviceTestResult.value.total_latency_ms,
  );
});

function readableError(value: unknown): string {
  return value instanceof Error ? value.message : "操作失败，请稍后重试";
}

async function loadModels() {
  loading.value = true;
  error.value = "";
  try {
    models.value = (await modelApi.list()).items;
  } catch (value) {
    error.value = readableError(value);
  } finally {
    loading.value = false;
  }
}

function resetVerification() {
  verified.value = false;
  verifyMessage.value = "";
  verifyError.value = "";
  availableModels.value = [];
}

function invalidateModelVerification() {
  verified.value = false;
  verifyMessage.value = "模型名称或参数已变化，请重新验证模型调用";
  verifyError.value = "";
}

function assignDefaults() {
  Object.assign(form, {
    display_name: "",
    base_url: "",
    api_key: "",
    model_name: "",
    temperature: 0.1,
    top_p: 0.8,
    timeout_seconds: 30,
    max_retries: 1,
    max_concurrency: 4,
  });
}

function openCreate() {
  mode.value = "create";
  editing.value = null;
  assignDefaults();
  replaceCredential.value = false;
  showAdvanced.value = false;
  resetVerification();
  dialogVisible.value = true;
}

function assignModel(model: ManagedModel) {
  Object.assign(form, {
    display_name: model.display_name,
    base_url: model.base_url,
    api_key: "",
    model_name: model.model_name,
    temperature: model.temperature ?? 0.1,
    top_p: model.top_p ?? 0.8,
    timeout_seconds: model.timeout_seconds,
    max_retries: model.max_retries,
    max_concurrency: model.max_concurrency,
  });
}

function openEdit(model: ManagedModel) {
  mode.value = "edit";
  editing.value = model;
  assignModel(model);
  replaceCredential.value = false;
  showAdvanced.value = false;
  resetVerification();
  dialogVisible.value = true;
}

function openCopy(model: ManagedModel) {
  mode.value = "copy";
  editing.value = model;
  assignModel(model);
  form.display_name = `${model.display_name} 副本`;
  replaceCredential.value = true;
  showAdvanced.value = false;
  resetVerification();
  dialogVisible.value = true;
}

function startCredentialReplacement() {
  replaceCredential.value = true;
  form.api_key = "";
  resetVerification();
}

async function verify() {
  if (!canVerify.value || verifying.value) return;
  verifying.value = true;
  error.value = "";
  resetVerification();
  try {
    const result =
      mode.value === "edit" && editing.value
        ? await modelApi.verifyExisting(
            editing.value.model_uid,
            replaceCredential.value ? form.api_key : undefined,
          )
        : await modelApi.verifyNew(
            form.base_url,
            form.api_key,
            form.timeout_seconds,
            form.model_name || undefined,
            form.temperature,
            form.top_p,
          );
    availableModels.value = result.models;
    verified.value = result.model_verified;
    verifyMessage.value = result.message;
    if (result.verified_model_name) {
      form.model_name = result.verified_model_name;
    }
    if (!form.model_name && result.models.length === 1) {
      form.model_name = result.models[0];
      verifyMessage.value = `${result.message}；已发现唯一模型，请再次验证模型调用`;
    }
  } catch (value) {
    const message = readableError(value);
    verifyError.value = `连接验证失败：${message}`;
    ElMessage.error(verifyError.value);
  } finally {
    verifying.value = false;
  }
}

async function save() {
  if (!canSave.value || saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    if (mode.value === "edit" && editing.value) {
      const body: ModelUpdateInput = {
        display_name: form.display_name,
        temperature: form.temperature,
        top_p: form.top_p,
        timeout_seconds: form.timeout_seconds,
        max_retries: form.max_retries,
        max_concurrency: form.max_concurrency,
        ...(replaceCredential.value ? { api_key: form.api_key } : {}),
      };
      await modelApi.update(editing.value.model_uid, body);
      ElMessage.success("模型配置已更新");
    } else {
      await modelApi.create({ ...form });
      ElMessage.success("模型已添加并安全保存凭据");
    }
    dialogVisible.value = false;
    await loadModels();
  } catch (value) {
    error.value = readableError(value);
  } finally {
    saving.value = false;
  }
}

async function testSaved(model: ManagedModel) {
  if (verifying.value) return;
  verifying.value = true;
  error.value = "";
  try {
    const result = await modelApi.verifyExisting(model.model_uid);
    ElMessage.success(`${model.display_name}：${result.message}`);
    await loadModels();
  } catch (value) {
    error.value = readableError(value);
  } finally {
    verifying.value = false;
  }
}

function openServiceTest(model: ManagedModel) {
  serviceTestModel.value = model;
  serviceTestForm.question = "";
  serviceTestForm.reference_intent = "";
  serviceTestError.value = "";
  serviceTestResult.value = null;
  serviceTestElapsedMs.value = null;
  serviceTestVisible.value = true;
}

async function runServiceTest() {
  if (!canRunServiceTest.value || !serviceTestModel.value) return;
  serviceTesting.value = true;
  serviceTestError.value = "";
  serviceTestResult.value = null;
  serviceTestElapsedMs.value = null;
  const started = performance.now();
  try {
    serviceTestResult.value = await modelApi.testService(
      serviceTestModel.value.model_uid,
      {
        system_prompt: serviceTestForm.system_prompt.trim(),
        question: serviceTestForm.question.trim(),
        ...(serviceTestForm.reference_intent.trim()
          ? { reference_intent: serviceTestForm.reference_intent.trim() }
          : {}),
      },
    );
    serviceTestElapsedMs.value = Math.round(performance.now() - started);
  } catch (value) {
    serviceTestElapsedMs.value = Math.round(performance.now() - started);
    serviceTestError.value = readableError(value);
  } finally {
    serviceTesting.value = false;
  }
}

function formatDuration(value: number | null): string {
  if (value === null) return "—";
  return value >= 1000
    ? `${(value / 1000).toFixed(2)} s`
    : `${Math.round(value)} ms`;
}

async function setDefault(model: ManagedModel) {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    await modelApi.setDefault(model.model_uid);
    ElMessage.success(`已将“${model.display_name}”设为默认模型`);
    await loadModels();
  } catch (value) {
    error.value = readableError(value);
    loading.value = false;
  }
}

async function toggleEnabled(model: ManagedModel) {
  if (model.is_default && model.enabled) {
    error.value = "当前模型是默认模型，请先设置其他默认模型再禁用";
    return;
  }
  try {
    if (model.enabled) {
      await ElMessageBox.confirm(
        `禁用“${model.display_name}”后，新请求将不能使用该模型。`,
        "禁用模型",
        { confirmButtonText: "确认禁用", cancelButtonText: "取消" },
      );
      await modelApi.disable(model.model_uid);
      ElMessage.success("模型已禁用，历史记录不受影响");
    } else {
      await modelApi.enable(model.model_uid);
      ElMessage.success("模型已启用");
    }
    await loadModels();
  } catch (value) {
    if (value !== "cancel" && value !== "close") {
      error.value = readableError(value);
    }
  }
}

onMounted(() => void loadModels());
</script>

<template>
  <section class="model-management" v-loading="loading">
    <div class="page-heading">
      <div>
        <p class="page-description">
          添加并验证用于意图识别的模型连接，默认模型可随时切换。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">
        ＋ 添加模型
      </el-button>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      @close="error = ''"
    />

    <el-empty
      v-if="!loading && models.length === 0"
      description="还没有可用模型，请先添加一个模型"
    >
      <el-button type="primary" @click="openCreate">添加第一个模型</el-button>
    </el-empty>

    <div v-else class="model-grid">
      <article
        v-for="model in models"
        :key="model.model_uid"
        class="model-card"
        :class="{ disabled: !model.enabled, default: model.is_default }"
      >
        <div class="model-card-head">
          <div>
            <div class="model-title-row">
              <h3>{{ model.display_name }}</h3>
              <el-tag v-if="model.is_default" type="warning" effect="light">
                ★ 默认
              </el-tag>
            </div>
            <p class="model-name">{{ model.model_name }}</p>
          </div>
          <el-tag :type="model.enabled ? 'success' : 'info'" round>
            {{ model.enabled ? "● 可用" : "已禁用" }}
          </el-tag>
        </div>

        <dl class="model-meta">
          <div><dt>API 地址</dt><dd :title="model.base_url">{{ model.base_url }}</dd></div>
          <div>
            <dt>连接凭据</dt>
            <dd>{{ model.credential_hint ?? "已通过运行环境配置" }}</dd>
          </div>
        </dl>

        <div class="model-actions">
          <el-button
            type="primary"
            plain
            :disabled="!model.enabled"
            @click="openServiceTest(model)"
          >
            服务测试
          </el-button>
          <el-button @click="openEdit(model)">编辑</el-button>
          <el-button
            v-if="!model.is_default"
            :disabled="!model.enabled"
            @click="setDefault(model)"
          >
            设为默认
          </el-button>
          <el-dropdown trigger="click">
            <el-button>更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  :disabled="verifying"
                  @click="testSaved(model)"
                >
                  测试连接
                </el-dropdown-item>
                <el-dropdown-item @click="openCopy(model)">
                  基于此模型创建新模型
                </el-dropdown-item>
                <el-dropdown-item
                  :disabled="model.is_default && model.enabled"
                  @click="toggleEnabled(model)"
                >
                  {{ model.enabled ? "禁用模型" : "启用模型" }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </article>
    </div>

    <el-dialog
      v-model="dialogVisible"
      class="model-dialog"
      modal-class="model-dialog-overlay"
      :title="dialogTitle"
      width="min(540px, 94vw)"
      align-center
      lock-scroll
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form label-position="top" class="friendly-model-form" @submit.prevent="save">
        <h4>基本信息</h4>
        <el-form-item label="显示名称" required>
          <el-input
            v-model="form.display_name"
            placeholder="例如：通义千问 Plus"
            maxlength="128"
          />
        </el-form-item>
        <el-form-item label="API 地址" required>
          <el-input
            v-model="form.base_url"
            :disabled="identityLocked"
            placeholder="例如：https://api.example.com/v1"
            @input="resetVerification"
          />
          <span v-if="identityLocked" class="field-help">
            调用地址决定模型身份。如需修改，请基于当前模型创建新模型。
          </span>
        </el-form-item>

        <h4>连接凭据</h4>
        <template v-if="mode === 'edit' && !replaceCredential">
          <div class="credential-status">
            <span class="credential-check">✓</span>
            <div>
              <strong>API Key 已安全配置</strong>
              <p>{{ editing?.credential_hint ?? "凭据已配置" }}</p>
            </div>
            <el-button @click="startCredentialReplacement">更换 API Key</el-button>
          </div>
        </template>
        <el-form-item v-else label="API Key" required>
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="输入 API Key"
            @input="resetVerification"
          />
          <span class="field-help">API Key 将加密保存，保存后不会再次完整显示。</span>
        </el-form-item>

        <div class="verify-row">
          <el-button
            :loading="verifying"
            :disabled="!canVerify"
            @click="verify"
          >
            {{ verifying ? "正在验证..." : "验证连接" }}
          </el-button>
          <span v-if="verified" class="verify-success">✓ {{ verifyMessage }}</span>
        </div>
        <el-alert
          v-if="verifyError"
          class="verify-error"
          :title="verifyError"
          type="error"
          show-icon
          :closable="false"
        />

        <el-form-item label="模型名称" required>
          <el-select
            v-model="form.model_name"
            filterable
            allow-create
            default-first-option
            :disabled="identityLocked"
            placeholder="验证后选择，或手动输入模型名称"
            @change="invalidateModelVerification"
          >
            <el-option
              v-for="name in availableModels"
              :key="name"
              :label="name"
              :value="name"
            />
          </el-select>
          <span v-if="identityLocked" class="field-help">
            模型名称创建后不可修改。
          </span>
        </el-form-item>

        <h4>常用参数</h4>
        <div class="parameter-grid">
          <el-form-item label="Temperature">
            <el-input-number
              v-model="form.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              @change="invalidateModelVerification"
            />
          </el-form-item>
          <el-form-item label="Top P">
            <el-input-number
              v-model="form.top_p"
              :min="0.01"
              :max="1"
              :step="0.05"
              @change="invalidateModelVerification"
            />
          </el-form-item>
        </div>

        <button
          type="button"
          class="advanced-toggle"
          @click="showAdvanced = !showAdvanced"
        >
          高级设置 {{ showAdvanced ? "⌃" : "⌄" }}
        </button>
        <div v-if="showAdvanced" class="parameter-grid advanced-panel">
          <el-form-item label="超时时间（秒）">
            <el-input-number v-model="form.timeout_seconds" :min="1" :max="600" />
          </el-form-item>
          <el-form-item label="失败重试次数">
            <el-input-number v-model="form.max_retries" :min="0" :max="5" />
          </el-form-item>
          <el-form-item label="并发上限">
            <el-input-number v-model="form.max_concurrency" :min="1" :max="256" />
          </el-form-item>
        </div>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" :disabled="!canSave" @click="save">
            {{ mode === "edit" ? "保存修改" : "保存模型" }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="serviceTestVisible"
      class="service-test-dialog"
      :title="`模型服务测试 · ${serviceTestModel?.display_name ?? ''}`"
      width="min(860px, 94vw)"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div class="service-test-layout">
        <el-form
          label-position="top"
          class="service-test-form"
          @submit.prevent="runServiceTest"
        >
          <el-form-item label="自定义提示词" required>
            <el-input
              v-model="serviceTestForm.system_prompt"
              type="textarea"
              :rows="5"
              maxlength="8000"
              show-word-limit
              resize="vertical"
              :disabled="serviceTesting"
              placeholder="输入发送给模型的 System Prompt"
            />
          </el-form-item>
          <el-form-item label="问句" required>
            <el-input
              v-model="serviceTestForm.question"
              type="textarea"
              :rows="4"
              maxlength="4000"
              show-word-limit
              resize="vertical"
              :disabled="serviceTesting"
              placeholder="例如：我想制定一个减脂训练计划"
              @keydown.ctrl.enter="runServiceTest"
            />
          </el-form-item>
          <el-form-item label="参考意图（可选）">
            <el-input
              v-model="serviceTestForm.reference_intent"
              maxlength="256"
              :disabled="serviceTesting"
              placeholder="例如：start_training；仅用于结果对照，不会发送给模型"
            />
          </el-form-item>
          <div class="service-test-submit">
            <span>Ctrl + Enter 快速测试</span>
            <el-button
              type="primary"
              :loading="serviceTesting"
              :disabled="!canRunServiceTest"
              @click="runServiceTest"
            >
              {{ serviceTesting ? "正在识别..." : "开始测试" }}
            </el-button>
          </div>
        </el-form>

        <section class="service-test-output" aria-live="polite">
          <el-alert
            v-if="serviceTestError"
            :title="serviceTestError"
            type="error"
            show-icon
            :closable="false"
          />
          <div v-else-if="serviceTesting" class="service-test-empty">
            模型正在回答并分析用时…
          </div>
          <div v-else-if="!serviceTestResult" class="service-test-empty">
            测试完成后，这里会显示模型回答、参考意图对照和耗时分析。
          </div>
          <template v-else>
            <div class="service-test-result-heading">
              <h3>模型回答</h3>
              <el-tag type="success" effect="plain">调用完成</el-tag>
            </div>
            <pre class="service-test-answer">{{
              serviceTestResult.answer || "（模型返回了空回答）"
            }}</pre>

            <section
              v-if="serviceTestResult.reference_intent"
              class="reference-intent-result"
            >
              <div class="service-test-result-heading">
                <h3>参考意图对照</h3>
                <el-tag
                  v-if="serviceTestResult.reference_match !== null"
                  :type="serviceTestResult.reference_match ? 'success' : 'warning'"
                  effect="plain"
                >
                  {{ serviceTestResult.reference_match ? "一致" : "不一致" }}
                </el-tag>
                <el-tag v-else type="info" effect="plain">无法自动判断</el-tag>
              </div>
              <dl class="reference-intent-grid">
                <div>
                  <dt>参考意图</dt>
                  <dd>{{ serviceTestResult.reference_intent }}</dd>
                </div>
                <div>
                  <dt>回答中提取</dt>
                  <dd>
                    {{
                      serviceTestResult.recognized_intents.join("、") ||
                      "未提取到结构化意图"
                    }}
                  </dd>
                </div>
              </dl>
            </section>

            <section class="service-test-latency">
              <h3>完成识别用时分析</h3>
              <div class="service-test-metrics">
                <div>
                  <span>端到端用时</span>
                  <strong>{{ formatDuration(serviceTestElapsedMs) }}</strong>
                  <small>浏览器发送至收到回答</small>
                </div>
                <div>
                  <span>模型调用</span>
                  <strong>{{ formatDuration(serviceTestResult.provider_latency_ms) }}</strong>
                  <small>模型服务响应耗时</small>
                </div>
                <div>
                  <span>后端处理</span>
                  <strong>{{ formatDuration(serviceTestResult.application_latency_ms) }}</strong>
                  <small>读取配置、凭据与结果分析</small>
                </div>
                <div>
                  <span>网络与前端</span>
                  <strong>{{ formatDuration(clientOverheadMs) }}</strong>
                  <small>传输及浏览器处理</small>
                </div>
              </div>
              <div class="service-test-meta">
                <span>输入 Token {{ serviceTestResult.input_tokens ?? "—" }}</span>
                <span>输出 Token {{ serviceTestResult.output_tokens ?? "—" }}</span>
                <span>总 Token {{ serviceTestResult.total_tokens ?? "—" }}</span>
                <span>结束原因 {{ serviceTestResult.finish_reason ?? "—" }}</span>
              </div>
            </section>
          </template>
        </section>
      </div>

      <template #footer>
        <el-button @click="serviceTestVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </section>
</template>
