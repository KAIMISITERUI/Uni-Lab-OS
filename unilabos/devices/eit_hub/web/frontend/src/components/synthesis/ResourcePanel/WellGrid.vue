<template>
  <!--
    功能:
      可视化孔位矩阵, 包在白底+灰边框的容器里. row x col 网格, 每个孔位为可点击圆点.
      三态:
        - 未放入 (虚线圆, 无填充)
        - 已放入 (浅蓝填充圆 + 深蓝字, 与侧片实心蓝形成形态层级)
        - 禁用 (灰色, 禁止点击)
      行号 / 列字母: 默认浅蓝, active (整行/整列填满) 实心深蓝.
      底部 全选 / 取消 实体按钮.
  -->
  <div v-if="row > 0 && col > 0" class="well-grid-wrap">
    <table class="grid-table">
      <tbody>
        <tr v-for="r in displayRows" :key="`r-${r}`">
          <td class="row-label-cell">
            <span
              class="axis-btn row-btn"
              :class="{ active: rowAllFilled(r) }"
              @click="selectRow(r)"
            >{{ r }}</span>
          </td>
          <td v-for="c in col" :key="`c-${c}`" class="cell">
            <span
              class="well-dot"
              :class="stateClass(r, c)"
              @click="onWellClick(r, c)"
            >{{ wellLabel(r, c) }}</span>
          </td>
        </tr>
        <tr class="col-label-row">
          <td></td>
          <td v-for="c in col" :key="`cl-${c}`">
            <span
              class="axis-btn col-btn"
              :class="{ active: colAllFilled(c) }"
              @click="selectCol(c)"
            >{{ colLetter(c) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="actions">
      <el-button type="primary" plain size="small" @click="fillAll(true)">全选</el-button>
      <el-button size="small" @click="fillAll(false)">取消</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 功能:
 *   渲染托盘内孔位矩阵, v-model 绑定 wells 数组, 父组件持有完整状态.
 * 索引规则:
 *   slotIndex = (c - 1) * row + (r - 1) (列优先, 与 ntu-model.json layout {start:"lb", direction:"y"} 一致).
 *   纵轴渲染顺序为高到低 (row..1) 以匹配 web_code 显示效果 (12 在最上方).
 */
import { computed } from 'vue'
import type { WellInfo } from './types'

interface Props {
  row: number
  col: number
  wells: WellInfo[]
  // true 时孔位点击循环 empty → filled → disabled → empty (编辑资源 3 态);
  // false 时仅在 filled ↔ empty 之间切换 (录入资源 2 态), 默认 false 不破坏录入行为
  allowDisabled?: boolean
}
const props = withDefaults(defineProps<Props>(), { allowDisabled: false })
const emit = defineEmits<{
  (e: 'update:wells', val: WellInfo[]): void
}>()

const displayRows = computed(() => {
  const arr: number[] = []
  for (let r = props.row; r >= 1; r--) { arr.push(r) }
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

function stateClass (r: number, c: number): string {
  const w = getWell(r, c)
  if (w === undefined) { return 'empty' }
  return w.state
}

function onWellClick (r: number, c: number): void {
  const idx = indexOf(r, c)
  const w = props.wells[idx]
  if (w === undefined) { return }
  if (!props.allowDisabled && w.state === 'disabled') { return }
  const next = props.wells.slice()
  let nextState: WellInfo['state']
  if (props.allowDisabled) {
    // 编辑模式三态循环: empty → filled → disabled → empty
    nextState = w.state === 'empty' ? 'filled' : w.state === 'filled' ? 'disabled' : 'empty'
  } else {
    nextState = w.state === 'filled' ? 'empty' : 'filled'
  }
  next[idx] = { ...w, state: nextState }
  emit('update:wells', next)
}

function fillAll (filled: boolean): void {
  const next = props.wells.map((w) => {
    if (w.state === 'disabled') { return w }
    return { ...w, state: filled ? 'filled' : 'empty' as const }
  })
  emit('update:wells', next)
}

function selectRow (r: number): void {
  const rowWells = props.wells.filter((w) => w.rowIndex === r && w.state !== 'disabled')
  if (rowWells.length === 0) { return }
  const allFilled = rowWells.every((w) => w.state === 'filled')
  const targetState: 'filled' | 'empty' = allFilled ? 'empty' : 'filled'
  const next = props.wells.map((w) => {
    if (w.rowIndex !== r || w.state === 'disabled') { return w }
    return { ...w, state: targetState }
  })
  emit('update:wells', next)
}

function selectCol (c: number): void {
  const colWells = props.wells.filter((w) => w.colIndex === c && w.state !== 'disabled')
  if (colWells.length === 0) { return }
  const allFilled = colWells.every((w) => w.state === 'filled')
  const targetState: 'filled' | 'empty' = allFilled ? 'empty' : 'filled'
  const next = props.wells.map((w) => {
    if (w.colIndex !== c || w.state === 'disabled') { return w }
    return { ...w, state: targetState }
  })
  emit('update:wells', next)
}

function rowAllFilled (r: number): boolean {
  const rowWells = props.wells.filter((w) => w.rowIndex === r && w.state !== 'disabled')
  return rowWells.length > 0 && rowWells.every((w) => w.state === 'filled')
}

function colAllFilled (c: number): boolean {
  const colWells = props.wells.filter((w) => w.colIndex === c && w.state !== 'disabled')
  return colWells.length > 0 && colWells.every((w) => w.state === 'filled')
}
</script>

<style scoped>
.well-grid-wrap {
  /* 整体白底+灰框线包住孔位矩阵, 视觉成"托盘"质感 */
  display: inline-flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  background: #fff;
  border: 1px solid #e0e6f0;
  border-radius: 8px;
  padding: 14px;
}
.grid-table {
  border-collapse: separate;
  border-spacing: 4px;
}
.row-label-cell {
  width: 28px;
  text-align: center;
  padding: 0;
}
.axis-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  border: 1px solid #d9e8ff;
  background: #fff;
  color: #4a86ff;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.axis-btn:hover {
  background: #c2d8ff;
  border-color: #b8d0ff;
}
.axis-btn.active {
  /* 整行/整列全部填满 → 实心深蓝 + 白字, 与已填孔(浅蓝实心)形成"激活态"层级 */
  background: #4a86ff;
  border-color: #4a86ff;
  color: #fff;
}
.cell {
  padding: 0;
}
.well-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 9px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  border: 1px dashed #c0c4cc;
  color: #909399;
  background: #fff;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.well-dot:hover {
  border-color: #4a86ff;
}
.well-dot.filled {
  /* 已放入: 浅蓝填充 + 深蓝字 (参考用户截图风格), 与侧片实心蓝(#4a86ff) 视觉成层级 */
  background: #d9e8ff;
  border: 1px solid #b8d0ff;
  color: #4a86ff;
}
.well-dot.disabled {
  background: #f0f2f5;
  border: 1px solid #dcdfe6;
  color: #c0c4cc;
  cursor: not-allowed;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
