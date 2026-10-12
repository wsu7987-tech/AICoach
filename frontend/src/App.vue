<script setup lang="ts">
import { ElCard, ElContainer, ElHeader, ElMain, ElTag } from "element-plus";
</script>

<template>
  <ElContainer class="shell">
    <ElHeader class="header">
      <div>
        <p class="eyebrow">AI COACH</p>
        <h1>Intent Router</h1>
      </div>
      <ElTag type="success" effect="dark">Foundation</ElTag>
    </ElHeader>
    <ElMain>
      <ElCard shadow="never" class="welcome-card">
        <template #header>
          <span>研发后台骨架</span>
        </template>
        <p>前端入口已就绪，后续任务将在此接入配置、调试、观测与评测模块。</p>
        <div class="boundary-grid">
          <div>
            <strong>/api/v1</strong>
            <span>Runtime API</span>
          </div>
          <div>
            <strong>/api/admin</strong>
            <span>Admin API</span>
          </div>
        </div>
      </ElCard>
    </ElMain>
  </ElContainer>
</template>
