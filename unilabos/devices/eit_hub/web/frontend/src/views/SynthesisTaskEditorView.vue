<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  DocumentChecked,
  Minus,
  Plus,
  Refresh,
  Upload,
} from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type JobState,
  type ReactionTemplate,
  checkResource,
  fetchReactionTemplate,
  saveReactionTemplate,
  submitReactionTemplate,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'

type ActiveCell = {
  row: number
  col: number
}

type FillState = {
  active: boolean
  sourceRow: number
  targetRow: number
  col: number
}

const templateData = ref<ReactionTemplate | null>(null)
const currentJobId = ref('')
const loading = ref(false)
const chemicalLoading = ref(false)
const chemicalOptions = ref<ChemicalRow[]>([])
const activeCell = ref<ActiveCell | null>(null)
const fillState = reactive<FillState>({
  active: false,
  sourceRow: -1,
  targetRow: -1,
  col: -1,
})

const experimentCount = computed(() => templateData.value?.rows.length || 12)

async function loadTemplate() {
  loading.value = true
  try {
    templateData.value = await fetchReactionTemplate()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function searchChemicals(query: string) {
  chemicalLoading.value = true
  try {
    const data = await listChemicals({
      q: query.trim() !== '' ? query.trim() : undefined,
      query_type: 'name',
      page: 1,
      page_size: 50,
    })
    chemicalOptions.value = data.items
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    chemicalLoading.value = false
  }
}

async function saveTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    templateData.value = await saveReactionTemplate(templateData.value)
    ElMessage.success('模板已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function runResourceCheck() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await checkResource(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('物料核算已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function submitTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await submitReactionTemplate(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('提交任务已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function onJobFinished(_job: JobState) {
  loadTemplate()
}

function isYesNoParam(name: string): boolean {
  return ['等待目标温度', '固定加料顺序', '自动加磁子'].includes(name)
}

function isReactorParam(name: string): boolean {
  return name === '反应器类型'
}

function isReagentNameColumn(header: string, index: number): boolean {
  if (index === 0) {
    return false
  }
  return header.includes('试剂') && header.includes('量') === false
}

function setExperimentCount(count: number) {
  if (templateData.value === null) {
    return
  }
  const width = templateData.value.headers.length
  const nextRows: unknown[][] = []
  for (let index = 0; index < count; index += 1) {
    const source = templateData.value.rows[index]
    const row = Array.isArray(source) ? [...source] : []
    while (row.length < width) {
      row.push('')
    }
    row[0] = index + 1
    nextRows.push(row.slice(0, width))
  }
  templateData.value.rows = nextRows
}

function addReagentPair() {
  if (templateData.value === null) {
    return
  }
  templateData.value.headers.push('试剂', '试剂量')
  for (const row of templateData.value.rows) {
    row.push('', '')
  }
  templateData.value.reagent_pair_count += 1
}

function removeReagentPair() {
  if (templateData.value === null) {
    return
  }
  if (templateData.value.reagent_pair_count <= 1) {
    ElMessage.warning('至少保留一组试剂列')
    return
  }
  templateData.value.headers.splice(templateData.value.headers.length - 2, 2)
  for (const row of templateData.value.rows) {
    row.splice(row.length - 2, 2)
  }
  templateData.value.reagent_pair_count -= 1
}

function setActiveCell(row: number, col: number) {
  activeCell.value = { row, col }
}

function isActiveCell(row: number, col: number): boolean {
  return activeCell.value?.row === row && activeCell.value?.col === col
}

function isFillPreview(row: number, col: number): boolean {
  if (fillState.active === false || fillState.col !== col) {
    return false
  }
  const minRow = Math.min(fillState.sourceRow, fillState.targetRow)
  const maxRow = Math.max(fillState.sourceRow, fillState.targetRow)
  return row >= minRow && row <= maxRow
}

function startFill(row: number, col: number) {
  fillState.active = true
  fillState.sourceRow = row
  fillState.targetRow = row
  fillState.col = col
  window.addEventListener('mouseup', finishFill, { once: true })
}

function hoverFillTarget(row: number, col: number) {
  if (fillState.active === false) {
    return
  }
  if (fillState.col !== col) {
    return
  }
  fillState.targetRow = row
}

function finishFill() {
  if (fillState.active === false || templateData.value === null) {
    resetFill()
    return
  }
  const sourceValue = templateData.value.rows[fillState.sourceRow]?.[fillState.col]
  const minRow = Math.min(fillState.sourceRow, fillState.targetRow)
  const maxRow = Math.max(fillState.sourceRow, fillState.targetRow)
  for (let rowIndex = minRow; rowIndex <= maxRow; rowIndex += 1) {
    if (rowIndex === fillState.sourceRow) {
      continue
    }
    templateData.value.rows[rowIndex][fillState.col] = sourceValue
  }
  resetFill()
}

function resetFill() {
  fillState.active = false
  fillState.sourceRow = -1
  fillState.targetRow = -1
  fillState.col = -1
}

onMounted(() => {
  loadTemplate()
  searchChemicals('')
})

onBeforeUnmount(() => {
  window.removeEventListener('mouseup', finishFill)
})
</script>

<template>
  <div class="view-stack" v-loading="loading">
    <section class="panel editor-settings-panel">
      <div class="panel-title">
        <h2>任务设定</h2>
        <div class="button-row">
          <el-select
            :model-value="experimentCount"
            style="width: 128px"
            @change="setExperimentCount"
          >
            <el-option
              v-for="count in templateData?.supported_experiment_counts || [12, 24, 36, 48]"
              :key="count"
              :label="String(count) + ' 个实验'"
              :value="count"
            />
          </el-select>
          <el-button :icon="Refresh" @click="loadTemplate">重载</el-button>
          <el-button type="primary" :icon="DocumentChecked" @click="saveTemplate">保存</el-button>
          <el-button type="warning" :icon="CircleCheck" @click="runResourceCheck">物料核算</el-button>
          <el-button type="success" :icon="Upload" @click="submitTemplate">提交任务</el-button>
        </div>
      </div>

      <div v-if="templateData !== null" class="settings-grid">
        <template v-for="item in templateData.param_rows" :key="item.name">
          <div v-if="item.type === 'section'" class="settings-section">{{ item.name }}</div>
          <el-form-item v-else :label="item.name" class="settings-item">
            <el-select v-if="isYesNoParam(item.name)" v-model="item.value" style="width: 100%">
              <el-option label="是" value="是" />
              <el-option label="否" value="否" />
            </el-select>
            <el-select v-else-if="isReactorParam(item.name)" v-model="item.value" style="width: 100%">
              <el-option label="heat" value="heat" />
            </el-select>
            <el-input v-else v-model="item.value" />
          </el-form-item>
        </template>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>试剂表格</h2>
        <div class="button-row">
          <el-button :icon="Plus" @click="addReagentPair">试剂列</el-button>
          <el-button :icon="Minus" @click="removeReagentPair">试剂列</el-button>
        </div>
      </div>

      <div v-if="templateData !== null" class="excel-wrap">
        <table class="excel-grid">
          <thead>
            <tr>
              <th v-for="(header, index) in templateData.headers" :key="`${header}-${index}`">
                {{ header }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in templateData.rows" :key="rowIndex">
              <td
                v-for="(header, colIndex) in templateData.headers"
                :key="colIndex"
                :class="{
                  'is-active': isActiveCell(rowIndex, colIndex),
                  'is-fill-preview': isFillPreview(rowIndex, colIndex),
                }"
                @mousedown="setActiveCell(rowIndex, colIndex)"
                @mouseenter="hoverFillTarget(rowIndex, colIndex)"
              >
                <el-input
                  v-if="colIndex === 0"
                  v-model="row[colIndex]"
                  disabled
                  class="excel-control"
                />
                <el-select
                  v-else-if="isReagentNameColumn(header, colIndex)"
                  v-model="row[colIndex]"
                  filterable
                  remote
                  reserve-keyword
                  clearable
                  class="excel-control"
                  :remote-method="searchChemicals"
                  :loading="chemicalLoading"
                  @focus="setActiveCell(rowIndex, colIndex)"
                >
                  <el-option
                    v-for="chem in chemicalOptions"
                    :key="chem.id"
                    :label="chem.substance || chem.substance_english_name || String(chem.id)"
                    :value="chem.substance || chem.substance_english_name || ''"
                  />
                </el-select>
                <el-input
                  v-else
                  v-model="row[colIndex]"
                  class="excel-control"
                  @focus="setActiveCell(rowIndex, colIndex)"
                />
                <button
                  v-if="isActiveCell(rowIndex, colIndex) && colIndex > 0"
                  class="fill-handle"
                  type="button"
                  @mousedown.stop.prevent="startFill(rowIndex, colIndex)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.editor-settings-panel {
  position: relative;
  z-index: 2;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(210px, 1fr));
  gap: 10px 14px;
  align-items: start;
}

.settings-section {
  grid-column: 1 / -1;
  padding: 8px 12px;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #eef4fb;
}

.settings-item {
  margin-bottom: 0;
}

.excel-wrap {
  width: 100%;
  max-height: calc(100vh - 430px);
  min-height: 360px;
  overflow: auto;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #ffffff;
}

.excel-grid {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
}

.excel-grid th,
.excel-grid td {
  min-width: 172px;
  width: 172px;
  height: 48px;
  padding: 6px;
  border: 1px solid #dce5f0;
  background: #ffffff;
  position: relative;
}

.excel-grid th:first-child,
.excel-grid td:first-child {
  left: 0;
  z-index: 2;
  min-width: 96px;
  width: 96px;
  text-align: center;
  position: sticky;
  background: #f8fbff;
}

.excel-grid th {
  top: 0;
  z-index: 3;
  color: #172033;
  font-size: 13px;
  font-weight: 700;
  position: sticky;
  background: #eef4fb;
}

.excel-grid th:first-child {
  z-index: 4;
}

.excel-grid td.is-active {
  outline: 2px solid #1a75cf;
  outline-offset: -2px;
}

.excel-grid td.is-fill-preview {
  background: #eaf3ff;
}

.excel-control {
  width: 100%;
}

.fill-handle {
  position: absolute;
  right: 1px;
  bottom: 1px;
  width: 9px;
  height: 9px;
  padding: 0;
  cursor: crosshair;
  border: 1px solid #ffffff;
  background: #1a75cf;
}

@media (max-width: 1100px) {
  .settings-grid {
    grid-template-columns: repeat(2, minmax(210px, 1fr));
  }
}

@media (max-width: 640px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>

