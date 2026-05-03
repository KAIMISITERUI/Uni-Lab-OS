<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElInput,
  ElRadio,
  ElRadioGroup,
} from 'element-plus'
import type { AiChoiceOption } from '../types'

interface Props {
  question: string
  options: AiChoiceOption[]
  multi: boolean
  allowOther: boolean
  allowSkip: boolean
  sending: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (event: 'confirm', answer: string | string[]): void
  (event: 'cancel'): void
}>()

// 单选: 选中的 option.value 或 'OTHER' 占位.
const singleValue = ref<string>('')
// 多选: 选中的 option.value 列表; 'OTHER' 表示用户开启了自定义输入.
const multiValues = ref<string[]>([])
// 自定义文本(allow_other 开启时启用)
const otherText = ref<string>('')

watch(
  () => [props.options, props.multi],
  () => {
    singleValue.value = ''
    multiValues.value = []
    otherText.value = ''
  },
  { immediate: true },
)

const otherActive = computed(() => {
  if (props.allowOther !== true) {
    return false
  }
  if (props.multi === true) {
    return multiValues.value.includes('__OTHER__')
  }
  return singleValue.value === '__OTHER__'
})

const canConfirm = computed(() => {
  if (props.sending === true) {
    return false
  }
  if (props.multi === true) {
    if (multiValues.value.length === 0) {
      return false
    }
    if (otherActive.value === true && otherText.value.trim() === '') {
      return false
    }
    return true
  }
  if (singleValue.value === '') {
    return false
  }
  if (singleValue.value === '__OTHER__' && otherText.value.trim() === '') {
    return false
  }
  return true
})

function buildAnswer(): string | string[] {
  if (props.multi === true) {
    const result: string[] = []
    for (const value of multiValues.value) {
      if (value === '__OTHER__') {
        result.push(otherText.value.trim())
      } else {
        result.push(value)
      }
    }
    return result
  }
  if (singleValue.value === '__OTHER__') {
    return otherText.value.trim()
  }
  return singleValue.value
}

function onConfirm(): void {
  if (canConfirm.value === false) {
    return
  }
  emit('confirm', buildAnswer())
}

function onSkip(): void {
  if (props.sending === true) {
    return
  }
  // 跳过: 单选返回空字符串, 多选返回空数组. 后端将其识别为 selected=null/[].
  emit('confirm', props.multi === true ? [] : '')
}

function onCancel(): void {
  if (props.sending === true) {
    return
  }
  emit('cancel')
}
</script>

<template>
  <div class="ai-choice-card">
    <div class="ai-choice-title">待你回答</div>
    <div class="ai-choice-question">{{ props.question }}</div>

    <ElRadioGroup
      v-if="props.multi !== true"
      v-model="singleValue"
      class="ai-choice-options"
      :disabled="props.sending"
    >
      <label
        v-for="option in props.options"
        :key="option.value"
        class="ai-choice-option"
        :class="{ 'ai-choice-option-active': singleValue === option.value }"
      >
        <ElRadio :value="option.value">
          <span class="ai-choice-option-label">{{ option.label }}</span>
          <span v-if="option.description" class="ai-choice-option-desc">{{ option.description }}</span>
        </ElRadio>
      </label>
      <label
        v-if="props.allowOther === true"
        class="ai-choice-option"
        :class="{ 'ai-choice-option-active': singleValue === '__OTHER__' }"
      >
        <ElRadio value="__OTHER__">
          <span class="ai-choice-option-label">其它(自定义)</span>
        </ElRadio>
      </label>
    </ElRadioGroup>

    <ElCheckboxGroup
      v-else
      v-model="multiValues"
      class="ai-choice-options"
      :disabled="props.sending"
    >
      <label
        v-for="option in props.options"
        :key="option.value"
        class="ai-choice-option"
        :class="{ 'ai-choice-option-active': multiValues.includes(option.value) }"
      >
        <ElCheckbox :value="option.value">
          <span class="ai-choice-option-label">{{ option.label }}</span>
          <span v-if="option.description" class="ai-choice-option-desc">{{ option.description }}</span>
        </ElCheckbox>
      </label>
      <label
        v-if="props.allowOther === true"
        class="ai-choice-option"
        :class="{ 'ai-choice-option-active': multiValues.includes('__OTHER__') }"
      >
        <ElCheckbox value="__OTHER__">
          <span class="ai-choice-option-label">其它(自定义)</span>
        </ElCheckbox>
      </label>
    </ElCheckboxGroup>

    <div v-if="otherActive" class="ai-choice-other">
      <ElInput
        v-model="otherText"
        :disabled="props.sending"
        placeholder="请输入自定义答案"
        clearable
      />
    </div>

    <div class="ai-choice-actions">
      <ElButton type="primary" :disabled="!canConfirm" :loading="props.sending" @click="onConfirm">
        确认
      </ElButton>
      <ElButton v-if="props.allowSkip === true" :disabled="props.sending" @click="onSkip">
        跳过
      </ElButton>
      <ElButton :disabled="props.sending" @click="onCancel">取消</ElButton>
    </div>
  </div>
</template>

<style scoped>
.ai-choice-card {
  width: 100%;
  box-sizing: border-box;
  padding: 12px 14px 14px;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-left: 4px solid #1a5fa8;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgba(18, 50, 90, 0.08);
  --el-color-primary: #1a5fa8;
}

.ai-choice-title {
  display: flex;
  align-items: center;
  min-height: 20px;
  color: #12325a;
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 8px;
  line-height: 1.4;
}

.ai-choice-question {
  font-size: 14px;
  color: #172033;
  margin-bottom: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.ai-choice-options {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin-bottom: 10px;
}

.ai-choice-option {
  /* 选项默认无边框无背景, 仅依赖 radio/checkbox 指示器, 与 Claude Code 选项卡一致. */
  display: flex;
  align-items: flex-start;
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.ai-choice-option:hover {
  background: rgba(26, 95, 168, 0.04);
}

.ai-choice-option-active {
  /* 选中后才出现淡蓝背景, 取消选中即恢复透明. */
  background: #eef6ff;
}

.ai-choice-option :deep(.el-radio),
.ai-choice-option :deep(.el-checkbox) {
  display: flex;
  align-items: flex-start;
  width: 100%;
  margin-right: 0;
  height: auto;
  min-height: 20px;
  white-space: normal;
}

.ai-choice-option :deep(.el-radio__input),
.ai-choice-option :deep(.el-checkbox__input) {
  flex: 0 0 auto;
  margin-top: 2px;
}

.ai-choice-option :deep(.el-radio__label),
.ai-choice-option :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  gap: 3px;
  padding-left: 9px;
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
}

.ai-choice-option-label {
  font-size: 13px;
  font-weight: 600;
  color: #172033;
}

.ai-choice-option-desc {
  font-size: 12px;
  color: #66758a;
  line-height: 1.4;
}

.ai-choice-other {
  margin-bottom: 10px;
}

.ai-choice-other :deep(.el-input__wrapper) {
  border-radius: 6px;
  box-shadow: 0 0 0 1px #dce5f0 inset;
}

.ai-choice-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.ai-choice-actions :deep(.el-button) {
  min-width: 72px;
  margin-left: 0;
}
</style>
