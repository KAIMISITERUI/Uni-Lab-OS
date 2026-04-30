<template>
  <!--
    功能:
      已选孔位的物质表格. 4 列对齐 web_code 截图: 孔位 / 介质内物质 / 物质的量 / 操作.
        - 介质内物质: el-select remote 化学品搜索 (调 listChemicals API)
        - 物质的量: el-input 数字 + 后缀单位下拉
        - 操作: 移除按钮, 把该 well state 重置为 empty
      托盘 vessel_models 为空 (Tip 类) 时父组件不挂载本组件.
  -->
  <div class="vessel-editor" v-if="filledWells.length > 0">
    <el-table :data="filledWells" size="small" border stripe :max-height="320">
      <el-table-column label="孔位" width="64" align="center" header-align="center">
        <template #default="{ row }">
          <span class="well-label">{{ row.colLabel }}{{ row.rowLabel }}</span>
        </template>
      </el-table-column>
      <el-table-column label="介质内物质" min-width="240" header-align="center">
        <template #default="{ row }">
          <el-select
            :model-value="row.chemical_id || ''"
            filterable
            remote
            clearable
            reserve-keyword
            placeholder="请输入物质名称"
            size="small"
            style="width: 100%"
            :teleported="true"
            popper-class="vessel-chem-popper"
            :remote-method="(q: string) => onChemicalSearch(row.slotIndex, q)"
            :loading="searchLoadingMap[row.slotIndex] === true"
            @change="(val: string | number | null) => onChemicalChange(row.slotIndex, val)"
          >
            <el-option
              v-for="opt in optionsMap[row.slotIndex] || mergeSelectedOption(row)"
              :key="opt.id"
              :label="formatLabel(opt)"
              :value="String(opt.id)"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="物质的量" min-width="160" header-align="center">
        <template #default="{ row }">
          <div class="amount-cell">
            <el-input-number
              :model-value="row.amount"
              :min="0"
              :controls="false"
              size="small"
              placeholder="请输入"
              class="amount-input"
              @update:model-value="(v: number | null | undefined) => updateWell(row.slotIndex, 'amount', v ?? null)"
            />
            <el-select
              :model-value="row.unit"
              size="small"
              class="unit-select"
              @update:model-value="(v: string) => updateWell(row.slotIndex, 'unit', v)"
            >
              <el-option v-for="u in unitOptions" :key="u" :label="u" :value="u" />
            </el-select>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="60" align="center" header-align="center">
        <template #default="{ row }">
          <el-button link type="danger" :icon="iconRemove" size="small" @click="onRemove(row.slotIndex)" />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import { Remove } from '@element-plus/icons-vue'
import { listChemicals, type ChemicalRow } from '@/api/chemicals'
import type { WellInfo } from './types'

interface Props {
  wells: WellInfo[]
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:wells', val: WellInfo[]): void
}>()

const iconRemove = Remove
const unitOptions = ['mg', 'g', 'mL', 'L', 'mmol', 'mol']

const filledWells = computed(() => props.wells.filter((w) => w.state === 'filled'))

// 每个 well 行独立的搜索状态, 支持并行查询不互相冲突
const optionsMap = reactive<Record<number, ChemicalRow[]>>({})
const searchLoadingMap = reactive<Record<number, boolean>>({})
const debounceTimerMap: Record<number, any> = {}

function formatLabel (opt: ChemicalRow): string {
  // 仅展示物质名称, 不再带 CAS 号
  return String(opt.substance || opt.substance_english_name || `#${opt.id}`)
}

// 当前选中项可能不在最新 options 列表里, 合并保证 el-select 能显示已选 label
function mergeSelectedOption (row: WellInfo): ChemicalRow[] {
  if (!row.chemical_id) { return [] }
  return [{ id: Number(row.chemical_id), substance: row.substance, cas_number: null }] as ChemicalRow[]
}

function onChemicalSearch (slotIndex: number, query: string): void {
  // 输入清空时不触发请求, 避免拉全表
  if (debounceTimerMap[slotIndex]) {
    clearTimeout(debounceTimerMap[slotIndex])
  }
  if (!query) {
    optionsMap[slotIndex] = []
    return
  }
  searchLoadingMap[slotIndex] = true
  debounceTimerMap[slotIndex] = setTimeout(async () => {
    try {
      // 使用化学品库统一模糊搜索, 让用户可按表格字段定位
      const resp = await listChemicals({ q: query, page_size: 30 })
      optionsMap[slotIndex] = resp.items || []
    } catch (err) {
      console.error('[VesselEditor] listChemicals failed:', err)
      optionsMap[slotIndex] = []
    } finally {
      searchLoadingMap[slotIndex] = false
    }
  }, 200)
}

function onChemicalChange (slotIndex: number, val: string | number | null): void {
  if (val === null || val === '' || val === undefined) {
    // 清空选择
    const next = props.wells.map((w) => {
      if (w.slotIndex !== slotIndex) { return w }
      return { ...w, chemical_id: '', substance: '' }
    })
    emit('update:wells', next)
    return
  }
  const opts = optionsMap[slotIndex] || []
  const opt = opts.find((o) => String(o.id) === String(val))
  const substance = opt?.substance || ''
  const next = props.wells.map((w) => {
    if (w.slotIndex !== slotIndex) { return w }
    return { ...w, chemical_id: String(val), substance }
  })
  emit('update:wells', next)
}

function updateWell (slotIndex: number, field: keyof WellInfo, value: unknown): void {
  const next = props.wells.map((w) => {
    if (w.slotIndex !== slotIndex) { return w }
    return { ...w, [field]: value }
  })
  emit('update:wells', next)
}

function onRemove (slotIndex: number): void {
  // 移除即把该 well 重置为 empty, 行为对齐 web_code VesselEditor: row.selected = false
  const next = props.wells.map((w) => {
    if (w.slotIndex !== slotIndex) { return w }
    return { ...w, state: 'empty' as const }
  })
  emit('update:wells', next)
}
</script>

<style>
/* 化学品搜索 dropdown z-index 必须高于 el-dialog (默认 2000+) 与背景试剂表, 否则会被遮 */
.vessel-chem-popper {
  z-index: 9999 !important;
}
</style>

<style scoped>
.vessel-editor {
  margin-top: 12px;
  border-top: 1px dashed #ebeef5;
  padding-top: 10px;
}
.well-label {
  font-size: 12px;
  font-weight: 600;
  color: #4a86ff;
}
.amount-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}
.amount-input {
  flex: 1 1 auto;
  width: auto;
}
.unit-select {
  flex: 0 0 70px;
}
.amount-cell :deep(.el-input-number .el-input__inner) {
  text-align: left;
}
</style>
