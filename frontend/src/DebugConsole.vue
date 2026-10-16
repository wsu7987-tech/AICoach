<script setup lang="ts">
import { ref } from "vue";
import { request } from "./configApi";

withDefaults(
  defineProps<{
    section?: "observability" | "status";
  }>(),
  { section: "observability" },
);

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
const status = ref<Record<string, unknown> | null>(null);
async function loadTraces() {
  traces.value = (
    await request<{ items: typeof traces.value }>("/traces?limit=30")
  ).items;
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
async function loadStatus() {
  status.value = await request<Record<string, unknown>>("/status/summary");
}
</script>
<template>
  <div class="debug-grid">
    <el-card v-if="section === 'status'"
      ><template #header>服务状态</template
      ><el-button @click="loadStatus">刷新</el-button>
      <pre v-if="status">{{ JSON.stringify(status, null, 2) }}</pre></el-card
    ><el-card v-if="section === 'observability'" class="wide"
      ><template #header>调用观测 / Replay</template
      ><el-button @click="loadTraces">刷新 Trace</el-button
      ><el-table :data="traces" style="width: 100%; margin-top: 12px"
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
    ><el-card v-if="section === 'observability'" class="wide"
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
