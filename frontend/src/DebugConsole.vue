<script setup lang="ts">
import { onMounted, ref } from "vue";
import { request } from "./configApi";
import { trafficSources } from "./statusApi";

const query = new URLSearchParams(window.location.search);
const source = ref(
  trafficSources.some((item) => item.value === query.get("source"))
    ? query.get("source")!
    : "",
);
const traceStatus = ref(
  ["success", "failed", "cancelled"].includes(query.get("status") ?? "")
    ? query.get("status")!
    : "",
);
const start = ref(query.get("start") ?? "");
const end = ref(query.get("end") ?? "");
const loading = ref(false);
const error = ref("");
const total = ref(0);

function windowLabel(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

type Trace = {
  trace_id: string;
  parent_trace_id?: string | null;
  attempts?: unknown[];
};
const traces = ref<
  { trace_id: string; input: string; route: string; status: string }[]
>([]);
const selected = ref<Trace | null>(null);
const left = ref("");
const right = ref("");
const diff = ref<unknown>(null);
async function loadTraces() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  const filters = new URLSearchParams();
  if (source.value) filters.set("source", source.value);
  if (traceStatus.value) filters.set("status", traceStatus.value);
  if (start.value) filters.set("start", start.value);
  if (end.value) filters.set("end", end.value);
  window.history.replaceState(
    {},
    "",
    `/observability${filters.size ? `?${filters}` : ""}`,
  );
  filters.set("limit", "30");
  try {
    const result = await request<{ items: typeof traces.value; total: number }>(
      `/traces?${filters}`,
    );
    traces.value = result.items;
    total.value = result.total;
  } catch (cause) {
    traces.value = [];
    total.value = 0;
    error.value = cause instanceof Error ? cause.message : "调用记录加载失败";
  } finally {
    loading.value = false;
  }
}
function clearFilters() {
  source.value = "";
  traceStatus.value = "";
  start.value = "";
  end.value = "";
  void loadTraces();
}
async function detail(id: string) {
  selected.value = await request<Trace>(`/traces/${id}`);
}
async function replay(id: string) {
  await request(`/traces/${id}/replay`, "POST", {
    mode: "historical",
    repeat: 1,
  });
  await loadTraces();
}
async function compare() {
  diff.value = await request("/traces/diff", "POST", {
    left_trace_id: left.value,
    right_trace_id: right.value,
  });
}
onMounted(() => void loadTraces());
</script>
<template>
  <div class="debug-grid">
    <el-card class="wide"
      ><template #header>调用观测 / Replay</template
      ><el-space wrap>
        <el-select
          v-model="source"
          aria-label="调用来源"
          placeholder="全部来源"
          clearable
          :disabled="loading"
          style="width: 150px"
          @change="loadTraces"
        >
          <el-option
            v-for="item in trafficSources"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select
          v-model="traceStatus"
          aria-label="调用状态"
          placeholder="全部状态"
          clearable
          :disabled="loading"
          style="width: 150px"
          @change="loadTraces"
        >
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="取消" value="cancelled" />
        </el-select>
        <el-button :loading="loading" @click="loadTraces">刷新 Trace</el-button>
        <el-button :disabled="loading" @click="clearFilters"
          >清除筛选</el-button
        >
      </el-space>
      <p v-if="start || end" class="trace-window">
        时间范围：{{ start ? windowLabel(start) : "不限" }} 至
        {{ end ? windowLabel(end) : "不限" }}
      </p>
      <p class="trace-window">
        共 {{ total }} 条，展示最近 {{ traces.length }} 条
      </p>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
        show-icon
      />
      <el-table :data="traces" style="width: 100%; margin-top: 12px"
        ><el-table-column prop="trace_id" label="Trace" /><el-table-column
          prop="input"
          label="输入"
        /><el-table-column prop="route" label="Route" /><el-table-column
          prop="status"
          label="状态"
        /><el-table-column label="操作"
          ><template #default="scope"
            ><el-button link @click="detail(scope.row.trace_id)">详情</el-button
            ><el-button link @click="replay(scope.row.trace_id)"
              >Replay</el-button
            ></template
          ></el-table-column
        ></el-table
      >
      <pre v-if="selected">{{
        JSON.stringify(selected, null, 2)
      }}</pre></el-card
    ><el-card class="wide"
      ><template #header>Trace Diff</template
      ><el-space wrap
        ><el-input v-model="left" placeholder="左 Trace ID" /><el-input
          v-model="right"
          placeholder="右 Trace ID"
        /><el-button @click="compare">对比</el-button></el-space
      >
      <pre v-if="diff">{{ JSON.stringify(diff, null, 2) }}</pre>
    </el-card>
  </div>
</template>
<style scoped>
.debug-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.wide {
  grid-column: 1 / -1;
}
.trace-window {
  color: #606266;
  font-size: 13px;
}
pre {
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  background: #f5f7fa;
  padding: 12px;
}
@media (max-width: 700px) {
  .debug-grid {
    grid-template-columns: 1fr;
  }
}
</style>
