<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  loadStatus,
  trafficSources,
  type CheckState,
  type ServiceStatus,
  type TrafficSource,
} from "./statusApi";

const emit = defineEmits<{
  navigate: [
    path: "/config/releases" | "/models" | "/observability",
    search?: string,
  ];
}>();
const data = ref<ServiceStatus | null>(null);
const source = ref<TrafficSource>("runtime");
const loading = ref(false);
const error = ref("");
let controller: AbortController | null = null;
let disposed = false;

const readinessChecks = [
  { key: "service", label: "数据库与表结构" },
  { key: "release", label: "发布配置" },
  { key: "model", label: "默认模型" },
] as const;
const readyState = computed<CheckState>(() =>
  data.value?.runtime_config_ready === true
    ? "ready"
    : data.value?.runtime_config_ready === false
      ? "not_ready"
      : "unavailable",
);
const labels: Record<CheckState, string> = {
  ready: "已就绪",
  not_ready: "未就绪",
  unavailable: "无法检查",
};
const tones = {
  ready: "success",
  not_ready: "danger",
  unavailable: "warning",
} as const;

function dateTime(value: string) {
  const date = new Date(
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`,
  );
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { hour12: false });
}
function number(value: number | null) {
  return value === null ? "—" : value.toLocaleString("zh-CN");
}
function latency(value: number | null) {
  return value === null
    ? "—"
    : `${Math.round(value).toLocaleString("zh-CN")} ms`;
}

async function refresh(reset = false) {
  if (loading.value) return;
  if (reset) data.value = null;
  loading.value = true;
  error.value = "";
  controller = new AbortController();
  const timeout = window.setTimeout(() => controller?.abort(), 15000);
  try {
    const result = await loadStatus(source.value, controller.signal);
    if (!disposed) data.value = result;
  } catch (cause) {
    if (!disposed) {
      error.value = controller.signal.aborted
        ? "状态请求超时，请检查服务连接后重试。"
        : cause instanceof Error
          ? `状态刷新失败：${cause.message}`
          : "状态刷新失败，请稍后重试。";
    }
  } finally {
    window.clearTimeout(timeout);
    if (!disposed) loading.value = false;
  }
}

function viewTraces(failed = false) {
  if (!data.value) return;
  const query = new URLSearchParams({
    source: data.value.source,
    start: data.value.window_start,
    end: data.value.checked_at,
  });
  if (failed) query.set("status", "failed");
  emit("navigate", "/observability", `?${query}`);
}

onMounted(() => void refresh());
onBeforeUnmount(() => {
  disposed = true;
  controller?.abort();
});
</script>

<template>
  <div class="status-page" :aria-busy="loading">
    <div class="status-toolbar">
      <div>
        <h2>运行概览</h2>
        <p aria-live="polite">
          {{ data ? `检查时间：${dateTime(data.checked_at)}` : "尚未获取状态" }}
          <span v-if="loading"> · 正在刷新</span>
        </p>
      </div>
      <el-button type="primary" :loading="loading" @click="refresh()"
        >刷新</el-button
      >
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="data && error"
      title="以下为上次检查结果，当前状态尚未确认。"
      type="warning"
      :closable="false"
    />
    <el-skeleton v-if="loading && !data" :rows="8" animated />

    <template v-if="data">
      <div class="status-cards">
        <el-card>
          <template #header><h3>就绪检查</h3></template>
          <div class="status-overview">
            <span>默认识别配置</span>
            <el-tag :type="tones[readyState]">{{ labels[readyState] }}</el-tag>
          </div>
          <div
            v-for="item in readinessChecks"
            :key="item.key"
            class="status-check"
          >
            <div>
              <strong>{{ item.label }}</strong>
              <p>{{ data.checks[item.key].message }}</p>
            </div>
            <el-tag :type="tones[data.checks[item.key].state]" effect="plain">
              {{ labels[data.checks[item.key].state] }}
            </el-tag>
          </div>
          <p class="status-note">
            就绪检查验证本地配置与凭据。模型服务的实际连通性需在模型管理中验证。
          </p>
        </el-card>

        <el-card>
          <template #header><h3>当前配置</h3></template>
          <div class="status-config">
            <div class="status-section-heading">
              <strong>生效版本</strong>
              <el-button
                link
                type="primary"
                @click="emit('navigate', '/config/releases')"
                >配置发布</el-button
              >
            </div>
            <template v-if="data.active_release">
              <div class="status-value">{{ data.active_release.version }}</div>
              <p>{{ data.active_release.note || "暂无发布说明" }}</p>
              <p class="status-note">
                发布于 {{ dateTime(data.active_release.created_at) }}
              </p>
            </template>
            <p v-else>{{ data.checks.release.message }}</p>
          </div>
          <div class="status-config">
            <div class="status-section-heading">
              <strong>默认模型</strong>
              <el-button
                link
                type="primary"
                @click="emit('navigate', '/models')"
                >模型管理</el-button
              >
            </div>
            <template v-if="data.default_model">
              <div class="status-value">
                {{ data.default_model.display_name }}
              </div>
              <p>{{ data.default_model.model_name }}</p>
              <el-tag v-if="!data.default_model.enabled" type="danger"
                >已停用</el-tag
              >
              <p v-if="data.checks.model.state !== 'ready'" class="status-note">
                {{ data.checks.model.message }}
              </p>
            </template>
            <p v-else>{{ data.checks.model.message }}</p>
          </div>
        </el-card>

        <el-card class="status-traffic">
          <template #header>
            <div class="status-section-heading">
              <h3>最近 24 小时调用</h3>
              <el-select
                v-model="source"
                aria-label="统计请求来源"
                :disabled="loading"
                style="width: 150px"
                @change="refresh(true)"
              >
                <el-option
                  v-for="item in trafficSources"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </div>
          </template>
          <el-alert
            v-if="data.checks.traffic.state !== 'ready'"
            :title="data.checks.traffic.message"
            type="warning"
            :closable="false"
          />
          <el-empty
            v-else-if="data.requests_24h === 0"
            description="该来源最近 24 小时暂无调用记录"
            :image-size="60"
          />
          <div class="status-metrics">
            <div>
              <span>请求数</span
              ><strong>{{ number(data.requests_24h) }}</strong>
            </div>
            <div>
              <span>失败数</span><strong>{{ number(data.errors_24h) }}</strong>
            </div>
            <div>
              <span>失败率</span
              ><strong>{{
                data.error_rate === null
                  ? "—"
                  : `${(data.error_rate * 100).toFixed(2)}%`
              }}</strong>
            </div>
            <div>
              <span>取消数</span
              ><strong>{{ number(data.cancelled_24h) }}</strong>
            </div>
            <div>
              <span>模型调用平均耗时</span
              ><strong>{{ latency(data.avg_latency_ms) }}</strong>
            </div>
            <div>
              <span>模型调用 P95</span
              ><strong>{{ latency(data.p95_latency_ms) }}</strong>
            </div>
          </div>
          <p class="status-note">
            统计范围：{{ dateTime(data.window_start) }} 至
            {{
              dateTime(data.checked_at)
            }}。仅统计已保存的调用记录；失败率为失败数 / 请求数，取消单独计数。
          </p>
          <p class="status-note">
            耗时为每次请求中模型调用尝试的累计时间，包含重试调用，不含排队、重试等待及其他处理时间。有效耗时样本：{{
              number(data.latency_samples)
            }}。
          </p>
          <el-space wrap>
            <el-button
              :disabled="data.checks.traffic.state !== 'ready'"
              @click="viewTraces()"
              >查看调用记录</el-button
            >
            <el-button
              :disabled="!data.errors_24h"
              type="danger"
              plain
              @click="viewTraces(true)"
              >查看失败请求</el-button
            >
          </el-space>
        </el-card>

        <el-card class="status-evaluation">
          <template #header><h3>评测任务</h3></template>
          <el-alert
            v-if="data.checks.evaluation.state !== 'ready'"
            :title="data.checks.evaluation.message"
            type="warning"
            :closable="false"
          />
          <div class="status-metrics">
            <div>
              <span>排队中</span
              ><strong>{{ number(data.evaluation_queued) }}</strong>
            </div>
            <div>
              <span>运行中</span
              ><strong>{{ number(data.evaluation_running) }}</strong>
            </div>
          </div>
          <p class="status-note">
            当前全部评测任务数量，不受调用来源筛选影响；运行中数量不代表任务仍有进展。
          </p>
        </el-card>
      </div>
      <el-collapse>
        <el-collapse-item title="查看状态详情" name="details">
          <pre class="status-json">{{ JSON.stringify(data, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </template>
    <el-empty v-else-if="!loading" description="无法获取服务状态，请刷新重试" />
  </div>
</template>

<style scoped>
.status-page {
  display: grid;
  gap: 18px;
}
.status-toolbar,
.status-section-heading,
.status-overview,
.status-check {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
h2,
h3,
p {
  margin: 0;
}
h2 {
  font-size: 20px;
}
h3 {
  font-size: 16px;
}
p {
  color: #606266;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.status-toolbar p {
  margin-top: 6px;
  font-size: 13px;
}
.status-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.status-overview {
  margin-bottom: 12px;
}
.status-check {
  padding: 15px 0;
  border-top: 1px solid #ebeef5;
}
.status-check p {
  margin-top: 5px;
  font-size: 13px;
}
.status-check .el-tag {
  flex-shrink: 0;
}
.status-config + .status-config {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}
.status-value {
  font-size: 20px;
  font-weight: 600;
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.status-traffic,
.status-evaluation {
  grid-column: 1 / -1;
}
.status-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin: 20px 0;
}
.status-metrics span {
  display: block;
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
}
.status-metrics strong {
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}
.status-note {
  font-size: 13px;
  margin: 12px 0;
}
.status-json {
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f5f7fa;
  padding: 16px;
}
@media (max-width: 800px) {
  .status-cards {
    grid-template-columns: 1fr;
  }
  .status-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .status-section-heading {
    flex-wrap: wrap;
  }
}
</style>
