<script setup lang="ts">
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus, Refresh, Upload } from '@element-plus/icons-vue'
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

const ANALYSIS_DRAFT_KEY = 'eit_hub.analysis_tables_draft'

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

const activeInstrument = ref<AnalysisInstrumentKey>('gc_ms')
const selectedRow = ref<number | null>(null)
const statusRows = ref<AnalysisStatusRow[]>([])
const statusLoading = ref(false)
const submitLoading = ref(false)
const currentJobId = ref('')

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
      status: '未查询',
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

function addRow() {
  tables[activeInstrument.value].push(createEmptyRow())
}

function deleteActiveRow() {
  if (selectedRow.value === null) {
    ElMessage.warning('请先选择要删除的样品行')
    return
  }
  const rows = tables[activeInstrument.value]
  if (rows.length <= 1) {
    ElMessage.warning('至少保留一行')
    return
  }
  rows.splice(selectedRow.value, 1)
  selectedRow.value = null
}

function clearActiveTable() {
  tables[activeInstrument.value] = createEmptyRows()
  selectedRow.value = null
  ElMessage.success('表格已清空')
}

function onJobFinished(_job: JobState) {
  refreshAnalysisContent()
}

function statusTagType(row: AnalysisStatusRow): 'success' | 'warning' | 'danger' | 'info' {
  const statusText = row.status.trim().toLowerCase()
  if (row.connected === true) {
    return 'success'
  }
  if (statusText === 'offline' || statusText === '未查询') {
    return 'info'
  }
  if (statusText === 'error' || statusText === 'unknown' || statusText === '') {
    return 'danger'
  }
  return 'warning'
}

function statusLabel(row: AnalysisStatusRow): string {
  const statusText = row.status.trim().toLowerCase()
  if (row.connected === true) {
    return '在线'
  }
  if (statusText === '未查询') {
    return '未查询'
  }
  if (statusText === 'offline') {
    return '离线'
  }
  return '异常'
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
        <div class="analysis-device-status">{{ row.status || 'Unknown' }}</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>分析样品表</h2>
        <div class="button-row">
          <el-button :icon="Refresh" :loading="statusLoading" @click="refreshAnalysisContent">刷新</el-button>
          <el-button :icon="Plus" @click="addRow">新增行</el-button>
          <el-button :icon="Delete" @click="deleteActiveRow">删除行</el-button>
          <el-button @click="clearActiveTable">清空表格</el-button>
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
              :model-value="tables[instrument.key]"
              :col-headers="[...csvHeaders]"
              :columns="analysisColumnsByInstrument[instrument.key]"
              :height="500"
              stretch-h="all"
              @selected-row="selectedRow = $event"
              @update:model-value="updateInstrumentRows(instrument.key, $event)"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" @finished="onJobFinished" />
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

.analysis-device-status {
  margin-top: 16px;
  color: #24344d;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 13px;
  word-break: break-word;
}

.analysis-tabs {
  min-width: 0;
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
