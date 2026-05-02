<script setup lang="ts">
import { computed, onActivated, ref, watch, type ComponentPublicInstance } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CopyDocument,
  Delete,
  DeleteFilled,
  DocumentChecked,
  Plus,
  Printer,
  Refresh,
  TrendCharts,
} from '@element-plus/icons-vue'
import EditableSpreadsheet from '../components/EditableSpreadsheet.vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type LabelPrinterConfig,
  type LabelPrinterProfile,
  type LabelPrinterProfileItem,
  fetchLabelProfile,
  fetchLabelProfiles,
  printLabels,
  saveLabelProfile,
  saveLabelProfileAs,
} from '../api/labelPrinter'
import { getErrorMessage } from '../api/http'

type SpreadsheetRow = Record<string, unknown> | unknown[]
type FillMode = 'increment' | 'copy'
type SelectedRowRange = {
  start: number
  end: number
}
type EditableSpreadsheetRef = ComponentPublicInstance & {
  fillSelectedRange: (mode: FillMode) => boolean
  clearSelectedRange: () => boolean
  getSelectedRowRange: () => SelectedRowRange | null
  syncSourceData: () => SpreadsheetRow[]
}

const DEFAULT_ROW_COUNT = 12

const profileItems = ref<LabelPrinterProfileItem[]>([])
const activeProfile = ref('')
const profileData = ref<LabelPrinterProfile | null>(null)
const config = ref<LabelPrinterConfig | null>(null)
const tableRows = ref<unknown[][]>(createEmptyRows(2, DEFAULT_ROW_COUNT))
const selectedRow = ref<number | null>(null)
const currentJobId = ref('')
const profilesLoading = ref(false)
const profileLoading = ref(false)
const saveLoading = ref(false)
const printLoading = ref(false)
const spreadsheetVersion = ref(0)
const spreadsheetRef = ref<EditableSpreadsheetRef | null>(null)

const columns = computed(() => {
  if (config.value === null) {
    return 1
  }
  return resolveColumns(config.value.paper.columns)
})

const columnHeaders = computed(() => {
  return Array.from({ length: columns.value }, (_item, index) => `第${index + 1}列`)
})

const spreadsheetColumns = computed<Array<Record<string, unknown>>>(() => {
  return columnHeaders.value.map((_header, index) => {
    return {
      data: index,
      type: 'text',
      width: 220,
    }
  })
})

const spreadsheetKey = computed(() => {
  return `${activeProfile.value || 'empty'}-${columns.value}-${spreadsheetVersion.value}`
})

async function loadProfiles() {
  profilesLoading.value = true
  try {
    const data = await fetchLabelProfiles()
    profileItems.value = data.items
    if (profileItems.value.length === 0) {
      activeProfile.value = ''
      profileData.value = null
      config.value = null
      tableRows.value = createEmptyRows(1, DEFAULT_ROW_COUNT)
      return
    }
    const profileExists = profileItems.value.some((item) => item.name === activeProfile.value)
    if (activeProfile.value === '' || profileExists === false) {
      activeProfile.value = profileItems.value[0].name
    }
    await loadProfile(activeProfile.value)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    profilesLoading.value = false
  }
}

async function loadProfile(name = activeProfile.value) {
  if (name === '') {
    return
  }
  profileLoading.value = true
  try {
    const data = await fetchLabelProfile(name)
    setProfileData(data, true)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    profileLoading.value = false
  }
}

function setProfileData(data: LabelPrinterProfile, resetRows: boolean) {
  profileData.value = data
  activeProfile.value = data.name
  config.value = cloneConfig(data.config)
  const nextColumns = resolveColumns(data.columns)
  if (resetRows === true) {
    tableRows.value = createEmptyRows(nextColumns, DEFAULT_ROW_COUNT)
  } else {
    tableRows.value = normalizeContentRows(tableRows.value, nextColumns)
  }
  selectedRow.value = null
  spreadsheetVersion.value += 1
}

async function saveCurrentProfile() {
  if (activeProfile.value === '' || config.value === null) {
    ElMessage.warning('请先选择标签模板')
    return
  }
  saveLoading.value = true
  try {
    const saved = await saveLabelProfile(activeProfile.value, {
      config: buildConfigPayload(),
    })
    setProfileData(saved, false)
    ElMessage.success('标签模板已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saveLoading.value = false
  }
}

async function saveProfileAs() {
  if (config.value === null) {
    ElMessage.warning('请先选择标签模板')
    return
  }
  try {
    const result = await ElMessageBox.prompt('请输入新模板文件名', '另存为', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: buildDefaultSaveAsName(),
      inputPattern: /^[^\\/:*?"<>|]+\.ya?ml$/i,
      inputErrorMessage: '文件名必须以 .yaml 或 .yml 结尾, 且不能包含路径',
    })
    const name = String(result.value || '').trim()
    if (name === '') {
      ElMessage.warning('模板文件名不能为空')
      return
    }
    saveLoading.value = true
    const saved = await saveLabelProfileAs({
      name,
      config: buildConfigPayload(),
    })
    await refreshProfileItems(saved.name)
    setProfileData(saved, false)
    ElMessage.success('标签模板已另存为')
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(getErrorMessage(error))
  } finally {
    saveLoading.value = false
  }
}

async function refreshProfileItems(selectedName: string) {
  const data = await fetchLabelProfiles()
  profileItems.value = data.items
  activeProfile.value = selectedName
}

function buildDefaultSaveAsName(): string {
  if (activeProfile.value === '') {
    return 'label_profile.yaml'
  }
  const dotIndex = activeProfile.value.lastIndexOf('.')
  if (dotIndex <= 0) {
    return `${activeProfile.value}_copy.yaml`
  }
  const stem = activeProfile.value.slice(0, dotIndex)
  const suffix = activeProfile.value.slice(dotIndex)
  return `${stem}_copy${suffix}`
}

function buildConfigPayload(): LabelPrinterConfig {
  if (config.value === null) {
    throw new Error('标签模板尚未加载')
  }
  const payload = cloneConfig(config.value)
  payload.paper.unit = 'mm'
  payload.paper.columns = resolveColumns(payload.paper.columns)
  return payload
}

async function addRow() {
  const rowCount = await promptAddRowCount()
  if (rowCount === null) {
    return
  }
  const rows = syncSpreadsheetRows()
  const rowRange = spreadsheetRef.value?.getSelectedRowRange() ?? null
  const insertIndex = getAddRowInsertIndex(rows, rowRange)
  const insertedRows = createEmptyRows(columns.value, rowCount)
  tableRows.value = [
    ...rows.slice(0, insertIndex),
    ...insertedRows,
    ...rows.slice(insertIndex),
  ]
  spreadsheetVersion.value += 1
}

async function promptAddRowCount(): Promise<number | null> {
  try {
    const result = await ElMessageBox.prompt('请输入要新增的行数', '新增行', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: '1',
      inputPattern: /^[1-9]\d*$/,
      inputErrorMessage: '请输入大于 0 的整数',
    })
    const rowCount = Number(result.value)
    if (Number.isInteger(rowCount) === false || rowCount <= 0) {
      ElMessage.warning('请输入大于 0 的整数')
      return null
    }
    return rowCount
  } catch {
    return null
  }
}

function getAddRowInsertIndex(rows: unknown[][], rowRange: SelectedRowRange | null): number {
  if (rowRange === null) {
    return rows.length
  }
  if (rows.length === 0) {
    return 0
  }
  const lastIndex = Math.max(rows.length - 1, 0)
  const endRow = Math.max(Math.min(rowRange.end, lastIndex), 0)
  return endRow + 1
}

function deleteActiveRow() {
  const rows = syncSpreadsheetRows()
  const rowRange = spreadsheetRef.value?.getSelectedRowRange() ?? null
  if (rows.length === 0) {
    ElMessage.warning('没有可删除的行')
    return
  }
  const lastIndex = rows.length - 1
  const startRow = rowRange !== null ? Math.max(Math.min(rowRange.start, lastIndex), 0) : lastIndex
  const endRow = rowRange !== null ? Math.max(Math.min(rowRange.end, lastIndex), startRow) : lastIndex
  tableRows.value = rows.filter((_row, rowIndex) => rowIndex < startRow || rowIndex > endRow)
  selectedRow.value = null
  spreadsheetVersion.value += 1
}

function clearSelectedContent() {
  if (spreadsheetRef.value === null) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  if (spreadsheetRef.value.clearSelectedRange() === true) {
    syncSpreadsheetRows()
    selectedRow.value = null
    ElMessage.success('选定内容已清除')
  }
}

function clearAllContent() {
  const rows = syncSpreadsheetRows()
  const rowCount = Math.max(rows.length, DEFAULT_ROW_COUNT)
  tableRows.value = createEmptyRows(columns.value, rowCount)
  selectedRow.value = null
  spreadsheetVersion.value += 1
  ElMessage.success('所有内容已清除')
}

function fillTable(mode: FillMode) {
  if (spreadsheetRef.value === null) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  spreadsheetRef.value.fillSelectedRange(mode)
}

async function printCurrentRows() {
  if (activeProfile.value === '') {
    ElMessage.warning('请先选择标签模板')
    return
  }
  const rows = syncSpreadsheetRows()
  printLoading.value = true
  try {
    const data = await printLabels({
      profile: activeProfile.value,
      rows,
    })
    currentJobId.value = data.job_id
    ElMessage.success('标签打印已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    printLoading.value = false
  }
}

function updateRows(rows: SpreadsheetRow[]) {
  tableRows.value = normalizeContentRows(rows, columns.value)
}

function syncSpreadsheetRows(): unknown[][] {
  if (spreadsheetRef.value !== null) {
    const rows = spreadsheetRef.value.syncSourceData()
    updateRows(rows)
  }
  return tableRows.value.map((row) => [...row])
}

function normalizeContentRows(rows: SpreadsheetRow[], width: number): unknown[][] {
  const nextRows: unknown[][] = []
  for (let index = 0; index < rows.length; index += 1) {
    nextRows.push(normalizeSpreadsheetRow(rows[index], width))
  }
  return nextRows
}

function normalizeSpreadsheetRow(row: SpreadsheetRow | undefined, width: number): unknown[] {
  const values = Array.isArray(row) === true ? [...row] : []
  while (values.length < width) {
    values.push('')
  }
  return values.slice(0, width)
}

function createEmptyRows(width: number, count: number): unknown[][] {
  const safeWidth = Math.max(resolveColumns(width), 1)
  return Array.from({ length: count }, () => Array.from({ length: safeWidth }, () => ''))
}

function cloneConfig(source: LabelPrinterConfig): LabelPrinterConfig {
  return JSON.parse(JSON.stringify(source)) as LabelPrinterConfig
}

function resolveColumns(value: unknown): number {
  const numericValue = Number(value)
  if (Number.isFinite(numericValue) === false || numericValue <= 0) {
    return 1
  }
  return Math.max(Math.trunc(numericValue), 1)
}

watch(
  () => config.value?.paper.columns,
  (nextValue, previousValue) => {
    if (config.value === null) {
      return
    }
    const nextColumns = resolveColumns(nextValue)
    if (config.value.paper.columns !== nextColumns) {
      config.value.paper.columns = nextColumns
      return
    }
    if (previousValue !== undefined && nextValue !== previousValue) {
      tableRows.value = normalizeContentRows(tableRows.value, nextColumns)
      spreadsheetVersion.value += 1
    }
  },
)

onActivated(() => {
  loadProfiles()
})
</script>

<template>
  <div class="view-stack">
    <section class="panel label-printer-panel" v-loading="profileLoading">
      <div class="panel-title">
        <h2>标签模板</h2>
        <div class="button-row">
          <el-button :icon="Refresh" :loading="profilesLoading" @click="loadProfiles">刷新</el-button>
          <el-button
            type="primary"
            :icon="DocumentChecked"
            :loading="saveLoading"
            @click="saveCurrentProfile"
          >
            保存
          </el-button>
          <el-button :icon="CopyDocument" :loading="saveLoading" @click="saveProfileAs">
            另存为
          </el-button>
        </div>
      </div>

      <div class="profile-toolbar">
        <el-form-item label="模板文件" class="profile-select-item">
          <el-select
            v-model="activeProfile"
            filterable
            :loading="profilesLoading"
            placeholder="选择模板文件"
            @change="loadProfile(String($event))"
          >
            <el-option
              v-for="item in profileItems"
              :key="item.name"
              :label="item.name"
              :value="item.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="当前路径" class="profile-path-item">
          <el-input
            :model-value="profileData?.path || ''"
            readonly
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 3 }"
          />
        </el-form-item>
      </div>

      <div v-if="config !== null" class="settings-grid">
        <div class="settings-left-column">
          <section class="settings-group printer-settings">
            <div class="settings-section">打印机参数</div>
            <div class="settings-group-fields">
              <el-form-item label="DPI" class="settings-item">
                <el-input-number v-model="config.printer.ppi" :min="1" :step="1" controls-position="right" />
              </el-form-item>
            </div>
          </section>

          <section class="settings-group position-settings">
            <div class="settings-section">位置微调</div>
            <div class="settings-group-fields">
              <el-form-item label="X(mm)" class="settings-item">
                <el-input-number v-model="config.position.x" :step="0.1" controls-position="right" />
              </el-form-item>
              <el-form-item label="Y(mm)" class="settings-item">
                <el-input-number v-model="config.position.y" :step="0.1" controls-position="right" />
              </el-form-item>
            </div>
          </section>
        </div>

        <section class="settings-group paper-settings">
          <div class="settings-section">纸张参数</div>
          <div class="settings-group-fields paper-fields">
            <el-form-item label="纸张宽度(mm)" class="settings-item">
              <el-input-number v-model="config.paper.width" :min="0.1" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="标签高度(mm)" class="settings-item">
              <el-input-number v-model="config.paper.height" :min="0.1" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="单位" class="settings-item">
              <el-input v-model="config.paper.unit" disabled />
            </el-form-item>
            <el-form-item label="列数" class="settings-item">
              <el-input-number v-model="config.paper.columns" :min="1" :step="1" controls-position="right" />
            </el-form-item>
            <el-form-item label="列间距(mm)" class="settings-item">
              <el-input-number v-model="config.paper.column_gap" :min="0" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="边距(mm)" class="settings-item">
              <el-input-number v-model="config.paper.margin" :min="0" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="间隙(mm)" class="settings-item">
              <el-input-number v-model="config.paper.gap" :min="0" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="间隙偏移(mm)" class="settings-item">
              <el-input-number v-model="config.paper.gap_offset" :step="0.1" controls-position="right" />
            </el-form-item>
            <el-form-item label="打印方向" class="settings-item">
              <el-select v-model="config.paper.direction" style="width: 100%">
                <el-option label="0" :value="0" />
                <el-option label="1" :value="1" />
              </el-select>
            </el-form-item>
          </div>
        </section>

        <section class="settings-group font-settings">
          <div class="settings-section">字体参数</div>
          <div class="settings-group-fields font-fields">
            <el-form-item label="字体名称" class="settings-item">
              <el-input v-model="config.font.name" />
            </el-form-item>
            <el-form-item label="字号上限(dot)" class="settings-item">
              <el-input-number v-model="config.font.size" :min="1" :step="1" controls-position="right" />
            </el-form-item>
            <el-form-item label="粗体" class="settings-item">
              <el-select v-model="config.font.bold" style="width: 100%">
                <el-option label="否" :value="0" />
                <el-option label="是" :value="1" />
              </el-select>
            </el-form-item>
            <el-form-item label="下划线" class="settings-item">
              <el-select v-model="config.font.underline" style="width: 100%">
                <el-option label="否" :value="0" />
                <el-option label="是" :value="1" />
              </el-select>
            </el-form-item>
            <el-form-item label="旋转角度" class="settings-item">
              <el-select v-model="config.font.rotation" style="width: 100%">
                <el-option label="0" :value="0" />
                <el-option label="90" :value="90" />
                <el-option label="180" :value="180" />
                <el-option label="270" :value="270" />
              </el-select>
            </el-form-item>
          </div>
        </section>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title label-table-title">
        <h2>标签内容</h2>
        <div class="button-row table-button-row">
          <el-button :icon="Plus" @click="addRow">新增行</el-button>
          <el-button :icon="Delete" @click="deleteActiveRow">删除行</el-button>
          <el-button :icon="Delete" @click="clearSelectedContent">清除内容</el-button>
          <el-button :icon="DeleteFilled" @click="clearAllContent">清除所有内容</el-button>
          <el-button :icon="TrendCharts" @click="fillTable('increment')">递增填充</el-button>
          <el-button :icon="CopyDocument" @click="fillTable('copy')">复制填充</el-button>
        </div>
      </div>

      <div class="spreadsheet-wrap">
        <EditableSpreadsheet
          :key="spreadsheetKey"
          ref="spreadsheetRef"
          :model-value="tableRows"
          :col-headers="columnHeaders"
          :columns="spreadsheetColumns"
          :height="500"
          stretch-h="all"
          @selected-row="selectedRow = $event"
          @update:model-value="updateRows"
        />
      </div>

      <div class="print-footer">
        <el-button
          class="print-button"
          type="primary"
          size="large"
          :icon="Printer"
          :loading="printLoading"
          @click="printCurrentRows"
        >
          打印
        </el-button>
      </div>
    </section>

    <JobPanel
      :job-id="currentJobId"
      source="label-printer"
      title="打印结果"
    />
  </div>
</template>

<style scoped>
.label-printer-panel {
  min-height: 260px;
}

.profile-toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 360px) minmax(0, 1fr);
  gap: 12px;
  align-items: end;
  margin-bottom: 14px;
}

.profile-select-item,
.profile-path-item {
  margin-bottom: 0;
}

.profile-select-item :deep(.el-select) {
  width: 100%;
}

.settings-grid {
  display: grid;
  grid-template-columns: minmax(180px, 0.6fr) minmax(0, 1.8fr);
  gap: 12px;
  align-items: start;
}

.settings-left-column {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.settings-group {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.font-settings {
  grid-column: 1 / -1;
}

.settings-section {
  min-height: 30px;
  padding: 6px 10px;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  background: #eef4fb;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}

.settings-group-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
  min-width: 0;
  padding-left: 10px;
}

.paper-fields {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.font-fields {
  grid-template-columns: minmax(180px, 1.4fr) repeat(4, minmax(120px, 1fr));
}

.settings-item {
  margin-bottom: 0;
}

.settings-item :deep(.el-form-item__label) {
  min-height: 24px;
  padding-bottom: 4px;
  line-height: 24px;
}

.settings-item :deep(.el-input-number) {
  width: 100%;
}

.label-table-title {
  align-items: flex-start;
}

.table-button-row {
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 0;
}

.table-button-row :deep(.el-button) {
  margin-left: 0;
}

.spreadsheet-wrap {
  width: 100%;
  min-height: 360px;
}

.print-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.print-button {
  min-width: 132px;
}

@media (max-width: 767.98px) {
  .label-printer-panel .panel-title,
  .label-table-title {
    flex-direction: column;
    align-items: flex-start;
  }

  .profile-toolbar,
  .settings-grid,
  .settings-group-fields,
  .paper-fields,
  .font-fields {
    grid-template-columns: 1fr;
  }

  .table-button-row {
    justify-content: flex-start;
  }

  .profile-path-item :deep(.el-input__inner) {
    text-overflow: clip;
  }

  .table-button-row :deep(.el-button) {
    flex: 1 1 calc(50% - 8px);
    min-width: 0;
    margin-left: 0;
  }

  .print-footer {
    justify-content: stretch;
  }

  .print-button {
    width: 100%;
    min-height: 48px;
  }

  .spreadsheet-wrap {
    min-height: 300px;
  }
}
</style>
