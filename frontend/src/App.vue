<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import ConfigCenter from "./ConfigCenter.vue";
import DebugConsole from "./DebugConsole.vue";
import IntentRecognition from "./IntentRecognition.vue";
import ModelManagement from "./ModelManagement.vue";

type AdminRoute =
  | "/intent"
  | "/debug"
  | "/observability"
  | "/config/routes"
  | "/config/intents"
  | "/config/slots"
  | "/config/enums"
  | "/config/examples"
  | "/config/prompt"
  | "/config/releases"
  | "/models"
  | "/status";

type NavigationItem = { path: AdminRoute; label: string };

const runtimeNavigation: NavigationItem[] = [
  { path: "/intent", label: "意图识别" },
  { path: "/debug", label: "单条调试" },
  { path: "/observability", label: "调用观测" },
  { path: "/status", label: "服务状态" },
];

const configDirectories: {
  id: string;
  label: string;
  children: NavigationItem[];
}[] = [
  {
    id: "config-intents",
    label: "意图管理",
    children: [
      { path: "/config/routes", label: "Route 管理" },
      { path: "/config/intents", label: "Intent 管理" },
    ],
  },
  {
    id: "config-parameters",
    label: "参数管理",
    children: [
      { path: "/config/slots", label: "Slot 管理" },
      { path: "/config/enums", label: "Enum / Alias 管理" },
    ],
  },
];

const configDirectNavigation: NavigationItem[] = [
  { path: "/config/examples", label: "样例管理" },
  { path: "/config/prompt", label: "提示词管理" },
  { path: "/config/releases", label: "配置发布" },
];

const systemNavigation: NavigationItem[] = [
  { path: "/models", label: "模型管理" },
];

const navigation = [
  ...runtimeNavigation,
  ...configDirectories.flatMap((group) => group.children),
  ...configDirectNavigation,
  ...systemNavigation,
];

function routeFromLocation(): AdminRoute {
  const rawPath = window.location.pathname.replace(/\/$/, "") || "/intent";
  const path = rawPath === "/config" ? "/config/routes" : rawPath;
  return navigation.some((item) => item.path === path) ? (path as AdminRoute) : "/intent";
}

const route = ref<AdminRoute>(routeFromLocation());
const current = computed(() => navigation.find((item) => item.path === route.value)!);
const configSection = computed(() => route.value.split("/").at(-1));

function navigate(path: AdminRoute) {
  if (path === route.value) return;
  window.history.pushState({}, "", path);
  route.value = path;
}

function handleMenuSelect(index: string) {
  const item = navigation.find((entry) => entry.path === index);
  if (item) navigate(item.path);
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
        <el-menu
          class="admin-menu"
          :default-active="route"
          :default-openeds="configDirectories.map((directory) => directory.id)"
          @select="handleMenuSelect"
        >
          <div class="admin-menu-group-label">运行调试</div>
          <el-menu-item
            v-for="item in runtimeNavigation"
            :key="item.path"
            :index="item.path"
          >
            {{ item.label }}
          </el-menu-item>

          <div class="admin-menu-group-label">配置中心</div>
          <el-sub-menu
            v-for="directory in configDirectories"
            :key="directory.id"
            :index="directory.id"
          >
            <template #title>{{ directory.label }}</template>
            <el-menu-item
              v-for="item in directory.children"
              :key="item.path"
              :index="item.path"
            >
              {{ item.label }}
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item
            v-for="item in configDirectNavigation"
            :key="item.path"
            :index="item.path"
          >
            {{ item.label }}
          </el-menu-item>

          <div class="admin-menu-group-label">系统配置</div>
          <el-menu-item
            v-for="item in systemNavigation"
            :key="item.path"
            :index="item.path"
          >
            {{ item.label }}
          </el-menu-item>
        </el-menu>
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
        <IntentRecognition v-if="route === '/intent'" @navigate="navigate" />
        <ModelManagement v-else-if="route === '/models'" />
        <ConfigCenter
          v-else-if="route.startsWith('/config/')"
          :section="configSection"
          @navigate="navigate"
        />
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
