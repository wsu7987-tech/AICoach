<script setup lang="ts">
import type { DraftJson } from "./configApi";
import type { ExpectedAction, ExpectedAnswer } from "./evaluationApi";

const props = defineProps<{
  modelValue?: ExpectedAnswer | null;
  configuration: DraftJson | null;
}>();
const emit = defineEmits<{ "update:modelValue": [value: ExpectedAnswer] }>();
function set(key: keyof ExpectedAnswer, value: unknown) {
  const next = { ...(props.modelValue ?? {}) };
  if (value === undefined || value === "") delete next[key];
  else Object.assign(next, { [key]: value });
  emit("update:modelValue", next);
}
function updateAction(index: number, patch: Partial<ExpectedAction>) {
  const actions = [...(props.modelValue?.actions ?? [])];
  actions[index] = { ...actions[index], ...patch };
  set("actions", actions);
}
function addAction() {
  set("actions", [...(props.modelValue?.actions ?? []), { route: "" }]);
}
function removeAction(index: number) {
  const actions = (props.modelValue?.actions ?? [])
    .filter((_, i) => i !== index)
    .map((action) => ({
      ...action,
      ...(action.depends_on
        ? {
            depends_on: action.depends_on
              .filter((value) => value !== index + 1)
              .map((value) => (value > index + 1 ? value - 1 : value)),
          }
        : {}),
    }));
  set("actions", actions.length ? actions : undefined);
}
function toggleIntent(index: number, checked: boolean) {
  const action = { ...props.modelValue!.actions![index] };
  if (checked) action.intent = null;
  else delete action.intent;
  const actions = [...props.modelValue!.actions!];
  actions[index] = action;
  set("actions", actions);
}
function setSlot(
  index: number,
  slotIndex: number,
  key: "name" | "value",
  value: string,
) {
  const slots = (props.modelValue?.actions?.[index].slots ?? []).map(
    (slot) => ({ ...slot }),
  );
  slots[slotIndex][key] = value;
  updateAction(index, { slots });
}
</script>

<template>
  <div class="expected-editor">
    <p class="muted">
      可选精确检查。未设置表示不检查；设置后必须与实际结果一致。标准答案的业务含义仍由模型或人工评审。
    </p>
    <div class="eval-form-grid">
      <el-form-item label="组合方式">
        <el-select
          :model-value="modelValue?.composition ?? ''"
          @update:model-value="set('composition', $event)"
        >
          <el-option label="不检查" value="" /><el-option
            label="单动作"
            value="single"
          />
          <el-option label="并行" value="parallel" /><el-option
            label="顺序"
            value="sequential"
          /><el-option label="备选" value="alternative" />
        </el-select>
      </el-form-item>
      <el-form-item label="是否追问">
        <el-select
          :model-value="modelValue?.need_clarification ?? ''"
          @update:model-value="set('need_clarification', $event)"
        >
          <el-option label="不检查" value="" /><el-option
            label="必须追问"
            :value="true"
          /><el-option label="不得追问" :value="false" />
        </el-select>
      </el-form-item>
      <el-form-item label="风险检查">
        <el-select
          :model-value="
            modelValue && 'risk' in modelValue
              ? modelValue.risk === null
                ? 'none'
                : 'risk'
              : ''
          "
          @update:model-value="
            set(
              'risk',
              $event === 'none'
                ? null
                : $event === 'risk'
                  ? { type: '', level: 'low' }
                  : undefined,
            )
          "
        >
          <el-option label="不检查" value="" /><el-option
            label="无风险"
            value="none"
          /><el-option label="指定风险" value="risk" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="modelValue?.risk" label="风险类型 / 等级">
        <el-input
          :model-value="modelValue.risk.type"
          placeholder="风险类型英文名称"
          @update:model-value="
            set('risk', { ...modelValue.risk, type: $event })
          "
        />
        <el-select
          :model-value="modelValue.risk.level"
          @update:model-value="
            set('risk', { ...modelValue.risk, level: $event })
          "
        >
          <el-option label="低" value="low" /><el-option
            label="中"
            value="medium"
          /><el-option label="高" value="high" />
        </el-select>
      </el-form-item>
    </div>
    <article
      v-for="(action, index) in modelValue?.actions ?? []"
      :key="index"
      class="eval-action-card"
    >
      <div class="eval-toolbar">
        <strong>期望动作 {{ index + 1 }}</strong
        ><el-button link type="danger" @click="removeAction(index)"
          >删除动作</el-button
        >
      </div>
      <div class="eval-form-grid">
        <el-form-item label="一级路由">
          <el-select
            :model-value="action.route"
            filterable
            allow-create
            default-first-option
            @update:model-value="
              updateAction(index, {
                route: $event,
                ...('intent' in action ? { intent: null } : {}),
              })
            "
          >
            <el-option
              v-for="route in configuration?.routes.filter(
                (item) => item.enabled,
              ) ?? []"
              :key="route.name"
              :label="route.zh"
              :value="route.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="二级意图">
          <el-checkbox
            :model-value="'intent' in action"
            @update:model-value="toggleIntent(index, !!$event)"
            >检查二级意图</el-checkbox
          >
          <el-select
            v-if="'intent' in action"
            :model-value="action.intent ?? ''"
            filterable
            allow-create
            default-first-option
            @update:model-value="
              updateAction(index, { intent: $event || null })
            "
          >
            <el-option label="明确无二级意图" value="" />
            <el-option
              v-for="intent in configuration?.intents.filter(
                (item) => item.enabled && item.route === action.route,
              ) ?? []"
              :key="intent.name"
              :label="intent.zh"
              :value="intent.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="依赖动作">
          <el-checkbox
            :model-value="action.depends_on != null"
            @update:model-value="
              updateAction(index, { depends_on: $event ? [] : undefined })
            "
            >检查依赖（空选为无依赖）</el-checkbox
          >
          <el-select
            v-if="action.depends_on != null"
            :model-value="action.depends_on"
            multiple
            @update:model-value="updateAction(index, { depends_on: $event })"
          >
            <el-option
              v-for="number in index"
              :key="number"
              :label="`动作 ${number}`"
              :value="number"
            />
          </el-select>
        </el-form-item>
      </div>
      <el-checkbox
        :model-value="action.slots != null"
        @update:model-value="
          updateAction(index, { slots: $event ? [] : undefined })
        "
        >精确检查该动作的全部参数（空列表表示无参数）</el-checkbox
      >
      <template v-if="action.slots != null">
        <div
          v-for="(slot, slotIndex) in action.slots"
          :key="slotIndex"
          class="eval-slot-row"
        >
          <el-input
            :model-value="slot.name"
            placeholder="参数名（英文）"
            @update:model-value="setSlot(index, slotIndex, 'name', $event)"
          />
          <el-input
            :model-value="slot.value"
            placeholder="标准值"
            @update:model-value="setSlot(index, slotIndex, 'value', $event)"
          />
          <el-button
            link
            type="danger"
            @click="
              updateAction(index, {
                slots: action.slots!.filter((_, i) => i !== slotIndex),
              })
            "
            >删除</el-button
          >
        </div>
        <el-button
          link
          type="primary"
          @click="
            updateAction(index, {
              slots: [...action.slots, { name: '', value: '' }],
            })
          "
          >添加参数</el-button
        >
      </template>
    </article>
    <el-button
      :disabled="(modelValue?.actions?.length ?? 0) >= 12"
      @click="addAction"
      >添加期望动作</el-button
    >
  </div>
</template>
