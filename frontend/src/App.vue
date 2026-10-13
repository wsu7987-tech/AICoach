<script setup lang="ts">
import ConfigCenter from "./ConfigCenter.vue";
</script>

<template>
  <el-container class="shell">
    <el-header class="header"
      ><div>
        <p class="eyebrow">AI COACH · ADMIN</p>
        <h1>Intent Router</h1>
      </div>
      <el-tag effect="dark">配置与 Release</el-tag></el-header
    >
    <el-main><ConfigCenter /></el-main>
  </el-container>
</template>
