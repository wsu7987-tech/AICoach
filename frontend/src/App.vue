<script setup lang="ts">
import ModelManagement from "./ModelManagement.vue";
</script>

<template>
  <el-container class="shell">
    <el-header class="header">
      <div>
        <p class="eyebrow">AI COACH</p>
        <h1>意图路由识别</h1>
      </div>
      <el-tag effect="dark">模型管理</el-tag>
    </el-header>
    <el-main>
      <nav class="primary-nav" aria-label="主导航">
        <span class="nav-brand">AI Coach</span>
        <span class="nav-item active">模型管理</span>
      </nav>
      <ModelManagement />
    </el-main>
  </el-container>
</template>
