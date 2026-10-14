<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import ConfigCenter from "./ConfigCenter.vue";
import DebugConsole from "./DebugConsole.vue";
import ModelManagement from "./ModelManagement.vue";

type AdminRoute = "/debug" | "/observability" | "/config" | "/models" | "/status";

const navigation: { path: AdminRoute; label: string; group: string }[] = [
  { path: "/debug", label: "单条调试", group: "运行调试" },
  { path: "/observability", label: "调用观测", group: "运行调试" },
  { path: "/status", label: "服务状态", group: "运行调试" },
  { path: "/config", label: "配置中心", group: "系统配置" },
  { path: "/models", label: "模型管理", group: "系统配置" },
];

function routeFromLocation(): AdminRoute {
  const path = window.location.pathname.replace(/\/$/, "") || "/models";
  return navigation.some((item) => item.path === path) ? (path as AdminRoute) : "/models";
}

const route = ref<AdminRoute>(routeFromLocation());
const current = computed(() => navigation.find((item) => item.path === route.value)!);
const groups = computed(() => [...new Set(navigation.map((item) => item.group))]);

function navigate(path: AdminRoute) {
  if (path === route.value) return;
  window.history.pushState({}, "", path);
  route.value = path;
}

function syncRoute() {
  route.value = routeFromLocation();
}

onMounted(() => {
  if (window.location.pathname.replace(/\/$/, "") !== route.value) {
    window.history.replaceState({}, "", route.value);
  }
  window.addEventListener("popstate", syncRoute);
});

onBeforeUnmount(() => window.removeEventListener("popstate", syncRoute));
</script>

<template>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <div class="admin-brand">
        <span class="brand-mark">AC</span>
        <div>
          <strong>AI Coach</strong>
          <small>Intent Router</small>
        </div>
      </div>

      <nav class="admin-navigation" aria-label="后台功能目录">
        <section v-for="group in groups" :key="group" class="nav-group">
          <p>{{ group }}</p>
          <a
            v-for="item in navigation.filter((entry) => entry.group === group)"
            :key="item.path"
            :href="item.path"
            :class="{ active: route === item.path }"
            :aria-current="route === item.path ? 'page' : undefined"
            @click.prevent="navigate(item.path)"
          >
            {{ item.label }}
          </a>
        </section>
      </nav>
    </aside>

    <main class="admin-content">
      <header class="content-header">
        <div>
          <p>AI COACH · ADMIN</p>
          <h1>{{ current.label }}</h1>
        </div>
        <el-tag effect="plain">研发后台</el-tag>
      </header>

      <section class="content-body">
        <ModelManagement v-if="route === '/models'" />
        <ConfigCenter v-else-if="route === '/config'" />
        <DebugConsole
          v-else
          :section="
            route === '/observability'
              ? 'observability'
              : route === '/status'
                ? 'status'
                : 'debug'
          "
        />
      </section>
    </main>
  </div>
</template>
