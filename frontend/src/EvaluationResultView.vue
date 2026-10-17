<script setup lang="ts">
import type { IntentResult } from "./intentApi";
defineProps<{ result: IntentResult | null }>();
const labels: Record<string, string> = {
  single: "单动作",
  parallel: "并行",
  sequential: "顺序",
  alternative: "备选",
};
</script>
<template>
  <div v-if="result" class="evaluation-actual">
    <p>
      <el-tag>{{ labels[result.composition] }}</el-tag> ·
      {{ result.actions.length }} 个动作
    </p>
    <article
      v-for="action in result.actions"
      :key="action.action_id"
      class="eval-action-card"
    >
      <strong
        >动作 {{ action.order }} ·
        {{ action.intent?.zh ?? "无二级意图" }}</strong
      >
      <p>
        {{ action.route
        }}<span v-if="action.intent"> / {{ action.intent.name }}</span>
      </p>
      <dl v-if="action.slots.length">
        <template v-for="(slot, index) in action.slots" :key="index"
          ><dt>{{ slot.zh || slot.name }}</dt>
          <dd>{{ slot.value }}</dd></template
        >
      </dl>
      <p v-else class="muted">无参数</p>
      <p v-if="action.depends_on.length">
        依赖：{{
          action.depends_on
            .map(
              (id) =>
                `动作 ${result!.actions.find((item) => item.action_id === id)?.order ?? id}`,
            )
            .join("、")
        }}
      </p>
    </article>
    <p>
      风险：{{
        result.risk ? `${result.risk.zh}（${result.risk.level}）` : "无"
      }}
    </p>
    <p>
      追问：{{ result.need_clarification ? result.clarification : "不追问" }}
    </p>
  </div>
  <el-empty v-else description="尚无有效识别结果" :image-size="60" />
</template>
