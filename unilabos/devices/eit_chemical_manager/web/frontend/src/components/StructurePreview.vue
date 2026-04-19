<script setup lang="ts">
import { ref, watch } from 'vue'
import { renderSmilesToSvg } from '../composables/useRDKit'

/**
 * 功能:
 *     根据 SMILES 渲染 2D 结构图的基础展示组件
 * 参数:
 *     smiles 待渲染的 SMILES 字符串, 空或无效时展示占位文案
 *     width/height 渲染尺寸(像素), 默认 160x120
 * 说明:
 *     - 内部维护 status 状态控制加载/成功/失败/空态的显示
 *     - 通过 useRDKit 的缓存避免重复解析, 列表大量行渲染也可接受
 */
interface Props {
  smiles?: string | null
  width?: number
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  smiles: '',
  width: 160,
  height: 120,
})

const svgContent = ref<string>('')
const status = ref<'empty' | 'loading' | 'ready' | 'invalid'>('empty')

async function render(): Promise<void> {
  const smiles = (props.smiles ?? '').trim()
  if (smiles === '') {
    // 空 SMILES 直接展示占位, 不触发 RDKit 加载
    svgContent.value = ''
    status.value = 'empty'
    return
  }
  status.value = 'loading'
  try {
    const svg = await renderSmilesToSvg(smiles, props.width, props.height)
    if (svg !== null) {
      svgContent.value = svg
      status.value = 'ready'
    } else {
      svgContent.value = ''
      status.value = 'invalid'
    }
  } catch {
    // RDKit 初始化或渲染异常, 统一降级为无效提示
    svgContent.value = ''
    status.value = 'invalid'
  }
}

// 初次挂载与参数变化时重新渲染
watch(
  () => [props.smiles, props.width, props.height],
  () => {
    render()
  },
  { immediate: true },
)
</script>

<template>
  <div
    class="structure-preview"
    :style="{ width: width + 'px', height: height + 'px' }"
  >
    <div v-if="status === 'empty'" class="hint placeholder">暂无结构</div>
    <div v-else-if="status === 'loading'" class="hint">加载中...</div>
    <div v-else-if="status === 'invalid'" class="hint error">结构解析失败</div>
    <div v-else class="svg-wrap" v-html="svgContent" />
  </div>
</template>

<style scoped>
.structure-preview {
  border: 1px solid var(--el-border-color-lighter);
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  overflow: hidden;
  border-radius: 4px;
}
.svg-wrap {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.svg-wrap :deep(svg) {
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
}
.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 4px;
  user-select: none;
}
.hint.error {
  color: var(--el-color-danger);
}
.hint.placeholder {
  color: var(--el-text-color-placeholder);
}
</style>
