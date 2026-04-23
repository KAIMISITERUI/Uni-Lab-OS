<script setup lang="ts">
import { computed, onActivated, reactive, ref, watch, type ComponentPublicInstance } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, DeleteFilled, Plus, Refresh, TrendCharts, Upload } from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type AnalysisInstrumentKey,
  type AnalysisMethodsRow,
  type AnalysisSampleRow,
  type AnalysisStatusRow,
  fetchAnalysisMethods,
  fetchAnalysisStatus,
  submitAnalysisTables,
} from '../api/analysis'
import { getErrorMessage } from '../api/http'
import { type JobState } from '../api/synthesis'
import EditableSpreadsheet from '../components/EditableSpreadsheet.vue'

const csvHeaders = [
  'SampleName',
  'AcqMethod',
  'RackCode',
  'VialPos',
  'SmplInjVol',
  'OutputFile',
] as const

type CsvHeader = (typeof csvHeaders)[number]
type CellValue = string | number | null

type AnalysisTableRow = Record<CsvHeader, CellValue>

type InstrumentMeta = {
  key: AnalysisInstrumentKey
  name: string
}

type SpreadsheetRow = Record<string, unknown> | unknown[]
type FillMode = 'increment' | 'copy'
type AutoAppendInstrumentKey = Extract<AnalysisInstrumentKey, 'uplc_qtof' | 'hplc'>
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

const ANALYSIS_DRAFT_KEY = 'eit_hub.analysis_tables_draft'
const AUTO_APPEND_INSTRUMENTS: AutoAppendInstrumentKey[] = ['uplc_qtof', 'hplc']

const instruments: InstrumentMeta[] = [
  { key: 'gc_ms', name: 'GC-MS' },
  { key: 'uplc_qtof', name: 'UPLC_QTOF' },
  { key: 'hplc', name: 'HPLC' },
]

const rackOptions = Array.from({ length: 6 }, (_item, index) => {
  const rackNumber = index + 1
  return {
    label: String(rackNumber),
    value: `Rack ${rackNumber}`,
  }
})
const rackValues = rackOptions.map((option) => option.value)

const methodOptions = reactive<Record<AnalysisInstrumentKey, string[]>>({
  gc_ms: [],
  uplc_qtof: [],
  hplc: [],
})

const analysisColumnsByInstrument = computed<Record<AnalysisInstrumentKey, Array<Record<string, unknown>>>>(
  () => ({
    gc_ms: buildAnalysisColumns('gc_ms'),
    uplc_qtof: buildAnalysisColumns('uplc_qtof'),
    hplc: buildAnalysisColumns('hplc'),
  }),
)

const tables = reactive<Record<AnalysisInstrumentKey, AnalysisTableRow[]>>({
  gc_ms: createEmptyRows(),
  uplc_qtof: createEmptyRows(),
  hplc: createEmptyRows(),
})

const autoAppendEnabled = reactive<Record<AutoAppendInstrumentKey, boolean>>({
  uplc_qtof: true,
  hplc: true,
})

const activeInstrument = ref<AnalysisInstrumentKey>('gc_ms')
const selectedRow = ref<number | null>(null)
const statusRows = ref<AnalysisStatusRow[]>([])
const statusLoading = ref(false)
const submitLoading = ref(false)
const currentJobId = ref('')
const spreadsheetRefs = ref<Partial<Record<AnalysisInstrumentKey, EditableSpreadsheetRef>>>({})

restoreAnalysisDraft()

const displayStatuses = computed(() =>
  instruments.map((instrument) => {
    const found = statusRows.value.find((row) => row.instrument === instrument.key)
    if (found !== undefined) {
      return found
    }
    return {
      instrument: instrument.key,
      name: instrument.name,
      host: '-',
      port: 0,
      raw_status: '',
      instrument_status: '未查询',
      message: '',
      total_sample_count: 0,
      unrun_sample_count: 0,
      connected: false,
    }
  }),
)

function createEmptyRow(): AnalysisTableRow {
  return {
    SampleName: '',
    AcqMethod: '',
    RackCode: '',
    VialPos: null,
    SmplInjVol: null,
    OutputFile: '',
  }
}

function createEmptyRows(count = 12): AnalysisTableRow[] {
  const rows: AnalysisTableRow[] = []
  for (let index = 0; index < count; index += 1) {
    rows.push(createEmptyRow())
  }
  return rows
}

function buildAnalysisColumns(instrument: AnalysisInstrumentKey): Array<Record<string, unknown>> {
  return csvHeaders.map((header) => {
    if (header === 'AcqMethod') {
      return {
        data: header,
        type: 'dropdown',
        source: createMethodSource(instrument),
        strict: false,
        allowInvalid: true,
        width: 200,
      }
    }
    if (header === 'RackCode') {
      return {
        data: header,
        type: 'dropdown',
        source: rackSource,
        strict: false,
        allowInvalid: true,
        width: 150,
      }
    }
    if (header === 'VialPos') {
      return {
        data: header,
        type: 'numeric',
        allowInvalid: true,
        width: 120,
        numericFormat: { pattern: '0' },
      }
    }
    if (header === 'SmplInjVol') {
      return {
        data: header,
        type: 'numeric',
        allowInvalid: true,
        width: 130,
      }
    }
    return {
      data: header,
      type: 'text',
      width: 200,
    }
  })
}

function rackSource(_query: string, process: (choices: string[]) => void) {
  process([...rackValues])
}

function createMethodSource(instrument: AnalysisInstrumentKey) {
  return (_query: string, process: (choices: string[]) => void) => {
    process([...methodOptions[instrument]])
  }
}

async function refreshAnalysisContent() {
  statusLoading.value = true
  try {
    const [statusResult, methodsResult] = await Promise.allSettled([
      fetchAnalysisStatus(),
      fetchAnalysisMethods(),
    ])
    if (statusResult.status === 'fulfilled') {
      statusRows.value = statusResult.value
    } else {
      ElMessage.error(getErrorMessage(statusResult.reason))
    }
    if (methodsResult.status === 'fulfilled') {
      applyMethodRows(methodsResult.value)
    } else {
      ElMessage.error(getErrorMessage(methodsResult.reason))
    }
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    statusLoading.value = false
  }
}

async function refreshAnalysisStatus(silent = false) {
  if (silent === false) {
    statusLoading.value = true
  }
  try {
    statusRows.value = await fetchAnalysisStatus()
  } catch (error) {
    if (silent === false) {
      ElMessage.error(getErrorMessage(error))
    }
  } finally {
    if (silent === false) {
      statusLoading.value = false
    }
  }
}

function applyMethodRows(rows: AnalysisMethodsRow[]) {
  const errors: string[] = []
  for (const row of rows) {
    if (row.error.trim() !== '') {
      errors.push(`${row.name}: ${row.error}`)
      continue
    }
    methodOptions[row.instrument] = row.methods
  }
  if (errors.length > 0) {
    ElMessage.error(`方法列表刷新失败: ${errors.join('; ')}`)
  }
}

async function submitTables() {
  submitLoading.value = true
  try {
    syncSpreadsheetRows()
    applyAutoAppendRows()
    const data = await submitAnalysisTables({ tables: buildSubmitPayload() })
    currentJobId.value = data.job_id
    ElMessage.success('分析任务已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    submitLoading.value = false
  }
}

function buildSubmitPayload(): Record<AnalysisInstrumentKey, AnalysisSampleRow[]> {
  return {
    gc_ms: tables.gc_ms.map(cloneRow),
    uplc_qtof: tables.uplc_qtof.map(cloneRow),
    hplc: tables.hplc.map(cloneRow),
  }
}

function cloneRow(row: AnalysisTableRow): AnalysisSampleRow {
  return {
    SampleName: row.SampleName,
    AcqMethod: row.AcqMethod,
    RackCode: row.RackCode,
    VialPos: row.VialPos,
    SmplInjVol: row.SmplInjVol,
    OutputFile: row.OutputFile,
  }
}

function syncSpreadsheetRows() {
  for (const instrument of instruments) {
    const spreadsheet = spreadsheetRefs.value[instrument.key]
    if (spreadsheet !== undefined) {
      const rows = spreadsheet.syncSourceData()
      updateInstrumentRows(instrument.key, rows)
    }
  }
}

function setSpreadsheetRef(
  instrument: AnalysisInstrumentKey,
  component: Element | ComponentPublicInstance | null,
) {
  if (component === null) {
    delete spreadsheetRefs.value[instrument]
    return
  }
  spreadsheetRefs.value[instrument] = component as EditableSpreadsheetRef
}

function getActiveSpreadsheet(): EditableSpreadsheetRef | undefined {
  return spreadsheetRefs.value[activeInstrument.value]
}

function syncActiveSpreadsheetRows(): AnalysisTableRow[] {
  const instrument = activeInstrument.value
  const spreadsheet = getActiveSpreadsheet()
  if (spreadsheet !== undefined) {
    const rows = spreadsheet.syncSourceData()
    updateInstrumentRows(instrument, rows)
  }
  return tables[instrument]
}

async function addRow() {
  const rowCount = await promptAddRowCount()
  if (rowCount === null) {
    return
  }
  const instrument = activeInstrument.value
  const spreadsheet = getActiveSpreadsheet()
  const rowRange = spreadsheet?.getSelectedRowRange() ?? null
  const rows = syncActiveSpreadsheetRows()
  const insertIndex = getAddRowInsertIndex(rows, rowRange)
  const insertedRows = createEmptyRows(rowCount)
  tables[instrument] = [
    ...rows.slice(0, insertIndex),
    ...insertedRows,
    ...rows.slice(insertIndex),
  ]
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

function getAddRowInsertIndex(rows: AnalysisTableRow[], rowRange: SelectedRowRange | null): number {
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
  const instrument = activeInstrument.value
  const spreadsheet = getActiveSpreadsheet()
  const rowRange = spreadsheet?.getSelectedRowRange() ?? null
  const rows = syncActiveSpreadsheetRows()
  if (rows.length === 0) {
    ElMessage.warning('没有可删除的行')
    return
  }
  const lastIndex = rows.length - 1
  const startRow = rowRange !== null ? Math.max(Math.min(rowRange.start, lastIndex), 0) : lastIndex
  const endRow = rowRange !== null ? Math.max(Math.min(rowRange.end, lastIndex), startRow) : lastIndex
  tables[instrument] = rows.filter((_row, rowIndex) => rowIndex < startRow || rowIndex > endRow)
  selectedRow.value = null
}

function clearActiveTable() {
  // 仅清除当前选区内单元格内容, 保留行结构, 与 "清除所有内容" 区分.
  const spreadsheet = getActiveSpreadsheet()
  if (spreadsheet === undefined) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  const cleared = spreadsheet.clearSelectedRange()
  if (cleared === false) {
    return
  }
  syncActiveSpreadsheetRows()
  selectedRow.value = null
  ElMessage.success('选定内容已清除')
}

function clearAllTables() {
  // 只清除当前仪器表格的全部行内容, 不影响其它仪器.
  const instrument = activeInstrument.value
  const rows = syncActiveSpreadsheetRows()
  tables[instrument] = createEmptyRows(rows.length)
  selectedRow.value = null
  ElMessage.success('所有内容已清除')
}

function fillActiveTable(mode: FillMode) {
  const spreadsheet = getActiveSpreadsheet()
  if (spreadsheet === undefined) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  spreadsheet.fillSelectedRange(mode)
}

function applyAutoAppendRows() {
  for (const instrument of AUTO_APPEND_INSTRUMENTS) {
    const { contentRows, trailingRows } = splitTrailingEmptyRows(tables[instrument])
    const rows = removeAutoAppendTail(instrument, contentRows)
    if (autoAppendEnabled[instrument] === false) {
      tables[instrument] = [...rows, ...trailingRows]
      continue
    }
    const lastSample = findLastCompleteManualSample(rows)
    if (lastSample === null) {
      tables[instrument] = [...rows, ...trailingRows]
      continue
    }
    tables[instrument] = [...rows, ...buildAutoAppendRows(instrument, lastSample), ...trailingRows]
  }
}

function splitTrailingEmptyRows(rows: AnalysisTableRow[]): {
  contentRows: AnalysisTableRow[]
  trailingRows: AnalysisTableRow[]
} {
  const lastContentIndex = findLastContentRowIndex(rows)
  if (lastContentIndex < 0) {
    return {
      contentRows: [],
      trailingRows: rows,
    }
  }
  return {
    contentRows: rows.slice(0, lastContentIndex + 1),
    trailingRows: rows.slice(lastContentIndex + 1),
  }
}

function findLastContentRowIndex(rows: AnalysisTableRow[]): number {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (hasRowContent(rows[index]) === true) {
      return index
    }
  }
  return -1
}

function removeAutoAppendTail(
  instrument: AutoAppendInstrumentKey,
  rows: AnalysisTableRow[],
): AnalysisTableRow[] {
  if (instrument === 'uplc_qtof') {
    if (rows.length > 0 && isAutoNamedRow(rows[rows.length - 1], 'wash_stop') === true) {
      return rows.slice(0, -1)
    }
    return rows
  }
  if (
    rows.length >= 2 &&
    isAutoNamedRow(rows[rows.length - 2], 'wash') === true &&
    isAutoNamedRow(rows[rows.length - 1], 'stop') === true
  ) {
    return rows.slice(0, -2)
  }
  return rows
}

function findLastCompleteManualSample(rows: AnalysisTableRow[]): AnalysisTableRow | null {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index]
    if (isKnownAutoAppendRow(row) === false && isCompleteSampleRow(row) === true) {
      return row
    }
  }
  return null
}

function buildAutoAppendRows(
  instrument: AutoAppendInstrumentKey,
  lastSample: AnalysisTableRow,
): AnalysisTableRow[] {
  if (instrument === 'uplc_qtof') {
    return [createAutoAppendRow('wash_stop', lastSample)]
  }
  return [
    createAutoAppendRow('wash', lastSample),
    createAutoAppendRow('stop', lastSample),
  ]
}

function createAutoAppendRow(name: string, lastSample: AnalysisTableRow): AnalysisTableRow {
  return {
    SampleName: name,
    AcqMethod: name,
    RackCode: lastSample.RackCode,
    VialPos: lastSample.VialPos,
    SmplInjVol: 0,
    OutputFile: name,
  }
}

function isAutoNamedRow(row: AnalysisTableRow, name: string): boolean {
  return (
    cellText(row.SampleName) === name &&
    cellText(row.AcqMethod) === name &&
    cellText(row.OutputFile) === name &&
    cellText(row.SmplInjVol) === '0'
  )
}

function isKnownAutoAppendRow(row: AnalysisTableRow): boolean {
  return (
    isAutoNamedRow(row, 'wash_stop') === true ||
    isAutoNamedRow(row, 'wash') === true ||
    isAutoNamedRow(row, 'stop') === true
  )
}

function isCompleteSampleRow(row: AnalysisTableRow): boolean {
  return csvHeaders.every((header) => isEmptyCell(row[header]) === false)
}

function hasRowContent(row: AnalysisTableRow): boolean {
  return csvHeaders.some((header) => isEmptyCell(row[header]) === false)
}

function isEmptyCell(value: CellValue): boolean {
  if (value === null) {
    return true
  }
  return String(value).trim() === ''
}

function cellText(value: CellValue): string {
  if (value === null) {
    return ''
  }
  return String(value).trim()
}

function onJobFinished(_job: JobState) {
  refreshAnalysisContent()
}

function onJobUpdated(_job: JobState) {
  refreshAnalysisStatus(true)
}

function statusTagType(row: AnalysisStatusRow): 'success' | 'warning' | 'danger' | 'info' {
  const instrumentStatus = row.instrument_status
  if (row.connected === true) {
    return 'success'
  }
  if (instrumentStatus === 'Offline' || instrumentStatus === '未查询') {
    return 'info'
  }
  if (instrumentStatus === 'Error' || instrumentStatus === 'Unknown' || instrumentStatus === '') {
    return 'danger'
  }
  return 'warning'
}

function statusLabel(row: AnalysisStatusRow): string {
  const instrumentStatus = row.instrument_status
  if (row.connected === true) {
    return '在线'
  }
  if (instrumentStatus === '未查询') {
    return '未查询'
  }
  if (instrumentStatus === 'Offline') {
    return '离线'
  }
  return '异常'
}

function sampleProgressText(row: AnalysisStatusRow): string {
  // 显示格式 "已运行/总数", 已运行 = 样品总数 - 未运行数.
  if (row.instrument_status === 'Idle' || row.total_sample_count <= 0) {
    return '-'
  }
  const finished = Math.max(row.total_sample_count - row.unrun_sample_count, 0)
  return `${finished}/${row.total_sample_count}`
}

function endpointText(row: AnalysisStatusRow): string {
  if (row.host === '-' || row.port === 0) {
    return '-'
  }
  return `${row.host}:${row.port}`
}

function updateInstrumentRows(instrument: AnalysisInstrumentKey, rows: SpreadsheetRow[]) {
  tables[instrument] = rows.map((row) => normalizeAnalysisRow(row))
}

function restoreAnalysisDraft() {
  try {
    const rawDraft = localStorage.getItem(ANALYSIS_DRAFT_KEY)
    if (rawDraft === null) {
      return
    }
    const draft = JSON.parse(rawDraft) as {
      activeInstrument?: AnalysisInstrumentKey
      tables?: Partial<Record<AnalysisInstrumentKey, AnalysisTableRow[]>>
      autoAppendEnabled?: Partial<Record<AutoAppendInstrumentKey, boolean>>
    }
    for (const instrument of instruments) {
      const rows = draft.tables?.[instrument.key]
      if (Array.isArray(rows) === true) {
        tables[instrument.key] = rows.map((row) => normalizeAnalysisRow(row))
      }
    }
    if (isAnalysisInstrumentKey(draft.activeInstrument) === true) {
      activeInstrument.value = draft.activeInstrument
    }
    for (const instrument of AUTO_APPEND_INSTRUMENTS) {
      const enabled = draft.autoAppendEnabled?.[instrument]
      if (typeof enabled === 'boolean') {
        autoAppendEnabled[instrument] = enabled
      }
    }
  } catch {
    localStorage.removeItem(ANALYSIS_DRAFT_KEY)
  }
}

function persistAnalysisDraft() {
  localStorage.setItem(
    ANALYSIS_DRAFT_KEY,
    JSON.stringify({
      activeInstrument: activeInstrument.value,
      tables: buildSubmitPayload(),
      autoAppendEnabled: { ...autoAppendEnabled },
    }),
  )
}

function isAnalysisInstrumentKey(value: unknown): value is AnalysisInstrumentKey {
  return instruments.some((instrument) => instrument.key === value)
}

function normalizeAnalysisRow(row: SpreadsheetRow): AnalysisTableRow {
  const source = buildRowSource(row)
  return {
    SampleName: normalizeTextCell(source.SampleName),
    AcqMethod: normalizeTextCell(source.AcqMethod),
    RackCode: normalizeTextCell(source.RackCode),
    VialPos: normalizeNumberCell(source.VialPos, true),
    SmplInjVol: normalizeNumberCell(source.SmplInjVol, false),
    OutputFile: normalizeTextCell(source.OutputFile),
  }
}

function buildRowSource(row: SpreadsheetRow): Record<CsvHeader, unknown> {
  if (Array.isArray(row) === true) {
    return {
      SampleName: row[0],
      AcqMethod: row[1],
      RackCode: row[2],
      VialPos: row[3],
      SmplInjVol: row[4],
      OutputFile: row[5],
    }
  }
  return row as Record<CsvHeader, unknown>
}

function normalizeTextCell(value: unknown): CellValue {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value)
}

function normalizeNumberCell(value: unknown, integerOnly: boolean): CellValue {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const numericValue = Number(value)
  if (Number.isFinite(numericValue) === false) {
    return String(value)
  }
  if (integerOnly === true) {
    return Math.trunc(numericValue)
  }
  return numericValue
}

onActivated(() => {
  refreshAnalysisContent()
})

watch(activeInstrument, () => {
  selectedRow.value = null
  persistAnalysisDraft()
})

watch(
  tables,
  () => {
    persistAnalysisDraft()
  },
  { deep: true },
)

watch(
  autoAppendEnabled,
  () => {
    persistAnalysisDraft()
  },
  { deep: true },
)
</script>

<template>
  <div class="view-stack">
    <section class="analysis-status-grid">
      <div v-for="row in displayStatuses" :key="row.instrument" class="analysis-status-card">
        <div class="analysis-status-main">
          <div>
            <div class="analysis-device-name">{{ row.name }}</div>
            <div class="analysis-device-endpoint">{{ endpointText(row) }}</div>
          </div>
          <el-tag :type="statusTagType(row)">{{ statusLabel(row) }}</el-tag>
        </div>
        <div class="analysis-device-details">
          <div class="analysis-detail-row">
            <span class="detail-label">仪器状态</span>
            <span class="detail-value">{{ row.instrument_status || 'Unknown' }}</span>
          </div>
          <div class="analysis-detail-row">
            <span class="detail-label">样品进度</span>
            <span class="detail-value">{{ sampleProgressText(row) }}</span>
          </div>
          <div v-if="row.message !== ''" class="analysis-detail-row detail-message">
            <span class="detail-label">消息</span>
            <span class="detail-value">{{ row.message }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>分析样品表</h2>
        <div class="button-row">
          <el-button :icon="Refresh" :loading="statusLoading" @click="refreshAnalysisContent">刷新</el-button>
          <el-button :icon="Plus" @click="addRow">新增行</el-button>
          <el-button :icon="Delete" @click="deleteActiveRow">删除行</el-button>
          <el-button @click="clearActiveTable">清除内容</el-button>
          <el-button :icon="DeleteFilled" @click="clearAllTables">清除所有内容</el-button>
          <el-button :icon="TrendCharts" @click="fillActiveTable('increment')">递增填充</el-button>
          <el-button :icon="CopyDocument" @click="fillActiveTable('copy')">复制填充</el-button>
          <el-button type="primary" :icon="Upload" :loading="submitLoading" @click="submitTables">
            保存并提交
          </el-button>
        </div>
      </div>

      <el-tabs v-model="activeInstrument" class="analysis-tabs">
        <el-tab-pane
          v-for="instrument in instruments"
          :key="instrument.key"
          :name="instrument.key"
          :label="instrument.name"
        >
          <div class="spreadsheet-wrap">
            <EditableSpreadsheet
              :key="instrument.key"
              :ref="(component) => setSpreadsheetRef(instrument.key, component)"
              :model-value="tables[instrument.key]"
              :col-headers="[...csvHeaders]"
              :columns="analysisColumnsByInstrument[instrument.key]"
              :height="500"
              stretch-h="all"
              @selected-row="selectedRow = $event"
              @update:model-value="updateInstrumentRows(instrument.key, $event)"
            />
          </div>
          <div v-if="instrument.key === 'uplc_qtof'" class="analysis-option-row">
            <el-checkbox v-model="autoAppendEnabled.uplc_qtof">
              自动添加冲柱+停机方法
            </el-checkbox>
          </div>
          <div v-if="instrument.key === 'hplc'" class="analysis-option-row">
            <el-checkbox v-model="autoAppendEnabled.hplc">
              自动添加冲柱+停机方法
            </el-checkbox>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <JobPanel
      :job-id="currentJobId"
      title="运行结果"
      @updated="onJobUpdated"
      @finished="onJobFinished"
    />
  </div>
</template>

<style scoped>
.analysis-status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(220px, 1fr));
  gap: 12px;
}

.analysis-status-card {
  min-height: 116px;
  padding: 16px;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(18, 50, 90, 0.06);
}

.analysis-status-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.analysis-device-name {
  color: #12325a;
  font-size: 16px;
  font-weight: 700;
}

.analysis-device-endpoint {
  margin-top: 8px;
  color: #66758a;
  font-size: 12px;
}

.analysis-device-details {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}

.analysis-detail-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #24344d;
}

.analysis-detail-row .detail-label {
  color: #66758a;
  font-size: 12px;
  flex-shrink: 0;
}

.analysis-detail-row .detail-value {
  font-family: "Cascadia Mono", Consolas, monospace;
  word-break: break-word;
  text-align: right;
}

.analysis-detail-row.detail-message .detail-value {
  color: #c15050;
}

.analysis-tabs {
  min-width: 0;
}

.analysis-option-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  min-height: 32px;
}

.spreadsheet-wrap {
  width: 100%;
  min-height: 380px;
}

@media (max-width: 1100px) {
  .analysis-status-grid {
    grid-template-columns: 1fr;
  }

  .spreadsheet-wrap {
    min-height: 320px;
  }
}
</style>
