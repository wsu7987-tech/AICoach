<script setup lang="ts">
import { ref } from "vue";
import ConfigCenter from "./ConfigCenter.vue";
import DebugConsole from "./DebugConsole.vue";

// Keep the established configuration-centre landing route stable; diagnostics
// are available from the adjacent first-level navigation item.
const page = ref("config");
</script>

<template>
  <el-container class="shell">
    <el-header class="header"
      ><div>
        <p class="eyebrow">AI COACH · ADMIN</p>
        <h1>Intent Router</h1>
      </div>
      <el-tag effect="dark">研发后台</el-tag></el-header
    >
    <el-main>
      <el-menu
        :default-active="page"
        mode="horizontal"
        @select="(key: string) => (page = key)"
      >
        <el-menu-item index="debug">单条调试</el-menu-item
        ><el-menu-item index="observability">调用观测</el-menu-item
        ><el-menu-item index="config">配置中心</el-menu-item
        ><el-menu-item index="status">服务状态</el-menu-item>
      </el-menu>
      <DebugConsole v-if="page !== 'config'" /><ConfigCenter v-else />
    </el-main>
  </el-container>
</template>
