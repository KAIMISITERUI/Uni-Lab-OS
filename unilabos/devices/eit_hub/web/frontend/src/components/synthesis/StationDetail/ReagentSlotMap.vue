<template>
  <!--
    功能:
      只读试剂盘位图. row x col 网格, 每个孔位为可点击圆点:
        - empty (虚线圆, 无填充, 不响应点击)
        - filled (浅蓝实心圆, 点击触发 select 事件)
        - disabled (灰色, 不响应)
      被选中孔位 (selectedSlotIndex) 加深蓝外圈, 用于二级试剂详情 Popover 锚点高亮.
      与 ResourcePanel/WellGrid.vue 索引规则一致 ((c-1)*row + (r-1)), 但去掉行/列批量按钮,
      纯展示+单选, 不修改 wells 数组.
  -->
  <div v-if="row > 0 && col > 0" class="reagent-slot-map">
    <table class="grid-table">
      <tbody>
        <tr v-for="r in displayRows" :key="`r-${r}`">
          <td class="row-label-cell">
            <span class="axis-label">{{ r }}</span>
          </td>
          <td v-for="c in col" :key="`c-${c}`" class="cell">
            <span
              ref="dotRefs"
              class="well-dot"
              :class="dotClass(r, c)"
              :data-slot-index="indexOf(r, c)"
              @click.stop="onWellClick(r, c)"
            >{{ wellLabel(r, c) }}</span>
          </td>
        </tr>
        <tr class="col-label-row">
          <td></td>
          <td v-for="c in col" :key="`cl-${c}`">
            <span class="axis-label">{{ colLetter(c) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WellInfo } from '../ResourcePanel/types'

interface Props {
  row: number
  col: number
  wells: WellInfo[]
  // 当前选中孔位索引 (受控). null 表示无选中
  selectedSlotIndex?: number | null
}
const props = withDefaults(defineProps<Props>(), { selectedSlotIndex: null })
const emit = defineEmits<{
  // 父组件根据该事件切换二级 Popover 内容; el 给 Popover 做 virtual-ref 锚点
  (e: 'select', payload: { slotIndex: number; well: WellInfo; el: HTMLElement }): void
}>()

const dotRefs = ref<HTMLElement[]>([])

// 顶部 → 底部 渲染顺序为高行号到低行号, 与 web_code/WellGrid 一致 (12 在最上方)
const displayRows = computed(() => {
  const arr: number[] = []
  for (let r = props.row; r >= 1; r--) {
    arr.push(r)
  }
  return arr
})

function colLetter (c: number): string {
  return String.fromCharCode(64 + c)
}

function wellLabel (r: number, c: number): string {
  return `${colLetter(c)}${r}`
}

function indexOf (r: number, c: number): number {
  return (c - 1) * props.row + (r - 1)
}

function getWell (r: number, c: number): WellInfo | undefined {
  return props.wells[indexOf(r, c)]
}

function dotClass (r: number, c: number): string {
  const w = getWell(r, c)
  if (w === undefined) {
    return 'empty'
  }
  const idx = indexOf(r, c)
  const selected = props.selectedSlotIndex === idx
  return `${w.state}${selected ? ' selected' : ''}`
}

function onWellClick (r: number, c: number): void {
  const idx = indexOf(r, c)
  const w = props.wells[idx]
  // 仅 filled 可点击, empty/disabled 忽略 (空孔位无可展示信息)
  if (w === undefined || w.state !== 'filled') {
    return
  }
  const el = dotRefs.value.find((node) => Number(node.dataset.slotIndex) === idx)
  if (el === undefined) {
    return
  }
  emit('select', { slotIndex: idx, well: w, el })
}

watch(
  () => props.wells,
  () => {
    // wells 变化后 dotRefs 由 v-for 自动重收集, 这里仅占位以便未来扩展
  },
)
</script>

<style scoped>
.reagent-slot-map {
  display: inline-flex;
  background: #fff;
  border: 1px solid #e0e6f0;
  border-radius: 6px;
  padding: 10px;
}
.grid-table {
  border-collapse: separate;
  border-spacing: 3px;
}
.row-label-cell {
  width: 22px;
  text-align: center;
  padding: 0;
}
.axis-label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  padding: 2px 4px;
  font-size: 11px;
  font-weight: 600;
  color: #4a86ff;
  user-select: none;
}
.cell {
  padding: 0;
}
.well-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 8px;
  font-weight: 600;
  user-select: none;
  border: 1px dashed #c0c4cc;
  color: #909399;
  background: #fff;
  transition: background 0.15s, border-color 0.15s, color 0.15s, box-shadow 0.15s;
}
.well-dot.filled {
  background: #d9e8ff;
  border: 1px solid #b8d0ff;
  color: #4a86ff;
  cursor: pointer;
}
.well-dot.filled:hover {
  border-color: #4a86ff;
  background: #c2d8ff;
}
.well-dot.disabled {
  background: #f0f2f5;
  border: 1px solid #dcdfe6;
  color: #c0c4cc;
}
.well-dot.selected {
  /* 二级 Popover 锚点高亮: 深蓝外圈, 与 filled 浅蓝填充叠加 */
  border-color: #1d4cd1;
  box-shadow: 0 0 0 2px rgba(29, 76, 209, 0.35);
  color: #1d4cd1;
}
</style>
