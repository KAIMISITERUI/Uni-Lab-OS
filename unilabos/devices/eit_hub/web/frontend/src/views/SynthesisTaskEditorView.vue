<script setup lang="ts">
import { computed, nextTick, onActivated, ref, watch, type ComponentPublicInstance } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  CopyDocument,
  Delete,
  DeleteFilled,
  DocumentChecked,
  Minus,
  Plus,
  Printer,
  Refresh,
  Tickets,
  TrendCharts,
  Upload,
} from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type BatchInTemplate,
  type JobState,
  type ParamRow,
  type ReactionTemplate,
  checkResource,
  fetchBatchInTemplate,
  fetchReactionTemplate,
  printBatchInReagentLabels,
  printBatchInTemplate,
  saveBatchInTemplate,
  saveReactionTemplate,
  submitReactionTemplate,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import {
  fetchAnalysisMethods,
  type AnalysisInstrumentKey,
  type AnalysisMethodsRow,
} from '../api/analysis'
import { getErrorMessage } from '../api/http'
import EditableSpreadsheet from '../components/EditableSpreadsheet.vue'

type SpreadsheetRow = Record<string, unknown> | unknown[]
type FillMode = 'increment' | 'copy'
type TemplateLoadOptions = {
  keepExperimentId?: boolean
}
type AnalysisParamName = 'GC_MS' | 'UPLC_QTOF' | 'HPLC'
type SettingsGroup = {
  title: string
  items: ParamRow[]
  isAnalysis: boolean
}
type EditableSpreadsheetRef = ComponentPublicInstance & {
  fillSelectedRange: (mode: FillMode) => boolean
  clearSelectedRange: () => boolean
  syncSourceData: () => SpreadsheetRow[]
}

const TASK_EDITOR_DRAFT_KEY = 'eit_hub.synthesis_task_editor_draft'
const EXPERIMENT_ID_PARAM_NAME = '实验ID'
const ANALYSIS_SECTION_TITLE = '分析方法设定'
const LEFT_SETTING_GROUP_TITLES = ['实验设定', '反应设定', '称量设定']
const ANALYSIS_PARAM_NAMES: AnalysisParamName[] = ['GC_MS', 'UPLC_QTOF', 'HPLC']
const ANALYSIS_PARAM_CONFIG: Record<
  AnalysisParamName,
  {
    instrument: AnalysisInstrumentKey
    label: string
  }
> = {
  GC_MS: {
    instrument: 'gc_ms',
    label: 'GC-MS',
  },
  UPLC_QTOF: {
    instrument: 'uplc_qtof',
    label: 'UPLC-QTOF',
  },
  HPLC: {
    instrument: 'hplc',
    label: 'HPLC',
  },
}

const templateData = ref<ReactionTemplate | null>(null)
const batchInData = ref<BatchInTemplate | null>(null)
const currentJobId = ref('')
const loading = ref(false)
const batchInLoading = ref(false)
const chemicalLoading = ref(false)
const methodsLoading = ref(false)
const spreadsheetRef = ref<EditableSpreadsheetRef | null>(null)
const batchInSpreadsheetRef = ref<EditableSpreadsheetRef | null>(null)
const autoGenerateBatchFile = ref(true)
const refreshBatchInAfterResourceCheck = ref(false)
const activeTableTab = ref<'reagent' | 'batchIn'>('reagent')
const batchInSpreadsheetVersion = ref(0)
const selectedBatchInRow = ref<number | null>(null)
const methodOptions = ref<Record<AnalysisInstrumentKey, string[]>>({
  gc_ms: [],
  uplc_qtof: [],
  hplc: [],
})
const analysisSampleSelectors = ref<Record<AnalysisParamName, string>>({
  GC_MS: '',
  UPLC_QTOF: '',
  HPLC: '',
})
let skipTemplatePersist = false

const experimentCount = computed(() => templateData.value?.rows.length || 12)

const analysisParamRows = computed<ParamRow[]>(() => {
  if (templateData.value === null) {
    return []
  }
  return templateData.value.param_rows.filter((item) => {
    return item.type === 'parameter' && isAnalysisMethodParam(item.name) === true
  })
})

const settingsGroups = computed<SettingsGroup[]>(() => {
  if (templateData.value === null) {
    return []
  }
  const groups: SettingsGroup[] = []
  let currentGroup: SettingsGroup | null = null
  for (const item of templateData.value.param_rows) {
    if (item.type === 'section') {
      currentGroup = {
        title: item.name,
        items: [],
        isAnalysis: isAnalysisSection(item.name),
      }
      groups.push(currentGroup)
      continue
    }
    if (isAnalysisMethodParam(item.name) === true) {
      continue
    }
    if (currentGroup === null) {
      currentGroup = {
        title: '实验参数',
        items: [],
        isAnalysis: false,
      }
      groups.push(currentGroup)
    }
    currentGroup.items.push(item)
  }
  for (const group of groups) {
    if (group.isAnalysis === true) {
      group.items = analysisParamRows.value
    }
  }
  return groups.filter((group) => group.items.length > 0 || group.isAnalysis === true)
})

const settingsColumns = computed<[SettingsGroup[], SettingsGroup[]]>(() => {
  const leftGroups: SettingsGroup[] = []
  const rightGroups: SettingsGroup[] = []
  for (const group of settingsGroups.value) {
    if (group.isAnalysis === true) {
      continue
    }
    if (LEFT_SETTING_GROUP_TITLES.includes(group.title) === true) {
      leftGroups.push(group)
      continue
    }
    rightGroups.push(group)
  }
  return [leftGroups, rightGroups]
})

const analysisSettingGroup = computed<SettingsGroup | null>(() => {
  return settingsGroups.value.find((group) => group.isAnalysis === true) ?? null
})

const spreadsheetColumns = computed<Array<Record<string, unknown>>>(() => {
  if (templateData.value === null) {
    return []
  }
  return templateData.value.headers.map((header, index) => {
    if (index === 0) {
      return {
        data: index,
        readOnly: true,
        width: 90,
      }
    }
    if (isReagentNameColumn(header, index) === true) {
      return {
        data: index,
        type: 'autocomplete',
        source: chemicalNameSource,
        strict: false,
        allowInvalid: true,
        width: 220,
      }
    }
    return {
      data: index,
      type: 'text',
      width: 180,
    }
  })
})

const spreadsheetKey = computed(() => {
  if (templateData.value === null) {
    return 'empty'
  }
  return `${templateData.value.headers.join('|')}-${templateData.value.rows.length}`
})

const batchInColumns = computed<Array<Record<string, unknown>>>(() => {
  if (batchInData.value === null) {
    return []
  }
  return batchInData.value.headers.map((header, index) => {
    const widthMap: Record<string, number> = {
      position: 110,
      tray_type: 320,
      content: 320,
      shelf_position: 120,
      storage: 240,
    }
    if (header === 'tray_type') {
      return {
        data: index,
        type: 'dropdown',
        source: batchInData.value?.tray_type_options || [],
        strict: false,
        allowInvalid: true,
        width: widthMap[header],
      }
    }
    return {
      data: index,
      type: 'text',
      width: widthMap[header] || 160,
    }
  })
})

const batchInSpreadsheetKey = computed(() => {
  if (batchInData.value === null) {
    return 'empty'
  }
  return `${batchInData.value.headers.join('|')}-${batchInData.value.rows.length}-${batchInSpreadsheetVersion.value}`
})

async function loadTemplate(useDraft = true, options: TemplateLoadOptions = {}) {
  loading.value = true
  try {
    const remoteTemplate = await fetchReactionTemplate()
    const draftTemplate = useDraft === true ? readTemplateDraft(remoteTemplate) : null
    if (useDraft !== true) {
      clearTemplateDraft()
    }
    setTemplateData(draftTemplate || remoteTemplate, options)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadBatchInTemplate() {
  batchInLoading.value = true
  try {
    setBatchInData(await fetchBatchInTemplate())
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    batchInLoading.value = false
  }
}

function reloadEditorData() {
  loadTemplate(false)
  loadBatchInTemplate()
}

async function loadAnalysisMethods() {
  methodsLoading.value = true
  try {
    applyMethodRows(await fetchAnalysisMethods())
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    methodsLoading.value = false
  }
}

function applyMethodRows(rows: AnalysisMethodsRow[]) {
  const nextOptions: Record<AnalysisInstrumentKey, string[]> = {
    gc_ms: [],
    uplc_qtof: [],
    hplc: [],
  }
  const errors: string[] = []
  for (const row of rows) {
    if (row.error.trim() !== '') {
      errors.push(`${row.name}: ${row.error}`)
      continue
    }
    nextOptions[row.instrument] = row.methods
  }
  methodOptions.value = nextOptions
  if (errors.length > 0) {
    ElMessage.error(`分析方法列表刷新失败: ${errors.join('; ')}`)
  }
}

async function loadChemicalNames(query: string): Promise<string[]> {
  chemicalLoading.value = true
  try {
    const data = await listChemicals({
      q: query.trim() !== '' ? query.trim() : undefined,
      query_type: 'name',
      page: 1,
      page_size: 50,
    })
    return buildChemicalNameOptions(data.items)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
    return []
  } finally {
    chemicalLoading.value = false
  }
}

function chemicalNameSource(query: string, process: (choices: string[]) => void) {
  void loadChemicalNames(query).then((choices) => {
    process(choices)
  })
}

function buildChemicalNameOptions(rows: ChemicalRow[]): string[] {
  const options = new Set<string>()
  for (const row of rows) {
    const name = String(row.substance || row.substance_english_name || '').trim()
    if (name !== '') {
      options.add(name)
    }
  }
  return Array.from(options)
}

async function saveTemplate() {
  if (templateData.value === null) {
    return
  }
  if (batchInData.value === null) {
    ElMessage.error('上料表格尚未加载')
    return
  }
  const templatePayload = buildActionTemplatePayload()
  const batchInPayload = buildBatchInPayload()
  if (templatePayload === null || batchInPayload === null) {
    return
  }
  try {
    const savedTemplate = await saveReactionTemplate(templatePayload)
    const savedBatchIn = await saveBatchInTemplate(batchInPayload)
    setTemplateData(savedTemplate)
    setBatchInData(savedBatchIn)
    void nextTick(() => {
      persistTemplateDraft()
    })
    ElMessage.success('任务和上料文件已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function saveReactionTemplateOnly() {
  if (templateData.value === null) {
    return
  }
  const templatePayload = buildActionTemplatePayload()
  if (templatePayload === null) {
    return
  }
  try {
    const savedTemplate = await saveReactionTemplate(templatePayload)
    setTemplateData(savedTemplate)
    void nextTick(() => {
      persistTemplateDraft()
    })
    ElMessage.success('试剂表格已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function saveBatchInTemplateOnly() {
  if (batchInData.value === null) {
    ElMessage.error('上料表格尚未加载')
    return
  }
  const batchInPayload = buildBatchInPayload()
  if (batchInPayload === null) {
    return
  }
  try {
    const savedBatchIn = await saveBatchInTemplate(batchInPayload)
    setBatchInData(savedBatchIn)
    ElMessage.success('上料表格已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function printReagentLabels() {
  if (batchInData.value === null) {
    ElMessage.error('上料表格尚未加载')
    return
  }
  const batchInPayload = buildBatchInPayload()
  if (batchInPayload === null) {
    return
  }
  try {
    const data = await printBatchInReagentLabels(batchInPayload)
    currentJobId.value = data.job_id
    ElMessage.success('打印试剂标签已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function printBatchInTable() {
  if (batchInData.value === null) {
    ElMessage.error('上料表格尚未加载')
    return
  }
  const batchInPayload = buildBatchInPayload()
  if (batchInPayload === null) {
    return
  }
  try {
    const data = await printBatchInTemplate(batchInPayload)
    currentJobId.value = data.job_id
    ElMessage.success('打印上料表格已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function runResourceCheck() {
  if (templateData.value === null) {
    return
  }
  const payload = buildActionTemplatePayload()
  if (payload === null) {
    return
  }
  try {
    refreshBatchInAfterResourceCheck.value = autoGenerateBatchFile.value
    const data = await checkResource({
      template: payload,
      auto_generate_batch_file: autoGenerateBatchFile.value,
    })
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
  const payload = buildActionTemplatePayload()
  if (payload === null) {
    return
  }
  try {
    const data = await submitReactionTemplate(payload)
    currentJobId.value = data.job_id
    ElMessage.success('上传任务已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function onJobFinished(job: JobState) {
  loadTemplate(false, { keepExperimentId: true })
  if (
    job.name === '物料核算' &&
    job.status === 'succeeded' &&
    refreshBatchInAfterResourceCheck.value === true
  ) {
    loadBatchInTemplate()
  }
  if (
    job.status === 'succeeded' &&
    (job.name === '打印试剂标签' || job.name === '打印上料表格')
  ) {
    loadBatchInTemplate()
  }
}

function buildActionTemplatePayload(): ReactionTemplate | null {
  if (templateData.value === null) {
    return null
  }
  syncTemplateSpreadsheet()
  if (validateAnalysisParams() === false) {
    return null
  }
  clearExperimentId(templateData.value)
  const payload = cloneReactionTemplate(templateData.value)
  serializeAnalysisParams(payload)
  clearExperimentId(payload)
  return payload
}

function buildBatchInPayload(): BatchInTemplate | null {
  if (batchInData.value === null) {
    return null
  }
  syncBatchInSpreadsheet()
  return cloneBatchInTemplate(batchInData.value)
}

function cloneReactionTemplate(data: ReactionTemplate): ReactionTemplate {
  return JSON.parse(JSON.stringify(data)) as ReactionTemplate
}

function cloneBatchInTemplate(data: BatchInTemplate): BatchInTemplate {
  return JSON.parse(JSON.stringify(data)) as BatchInTemplate
}

function clearExperimentId(data: ReactionTemplate) {
  for (const item of data.param_rows) {
    if (item.type === 'parameter' && item.name === EXPERIMENT_ID_PARAM_NAME) {
      item.value = ''
    }
  }
  data.params[EXPERIMENT_ID_PARAM_NAME] = ''
}

function serializeAnalysisParams(data: ReactionTemplate) {
  for (const item of data.param_rows) {
    if (item.type !== 'parameter' || isAnalysisMethodParam(item.name) === false) {
      continue
    }
    item.value = buildAnalysisMethodValue(item.name, item.value)
    data.params[item.name] = item.value
  }
}

function buildAnalysisMethodValue(name: AnalysisParamName, methodValue: unknown): string {
  const methodName = cellText(methodValue)
  if (methodName === '') {
    return ''
  }
  const selector = analysisSampleSelectors.value[name].trim()
  if (selector === '') {
    return methodName
  }
  return `${methodName}(${selector})`
}

function validateAnalysisParams(): boolean {
  if (templateData.value === null) {
    return false
  }
  for (const item of templateData.value.param_rows) {
    if (item.type !== 'parameter' || isAnalysisMethodParam(item.name) === false) {
      continue
    }
    const methodName = cellText(item.value)
    const selector = analysisSampleSelectors.value[item.name].trim()
    if (methodName === '' && selector !== '') {
      ElMessage.error(`请先选择 ${analysisInstrumentLabel(item.name)} 分析方法`)
      return false
    }
    if (isValidSampleSelector(selector) === false) {
      ElMessage.error(`检测样品格式错误: ${analysisInstrumentLabel(item.name)} 请填写 1, 1-8 或 1-8,10`)
      return false
    }
  }
  return true
}

function isValidSampleSelector(selector: string): boolean {
  const text = selector.trim()
  if (text === '') {
    return true
  }
  const tokens = text.split(',')
  for (const token of tokens) {
    const part = token.trim()
    if (part === '') {
      return false
    }
    const rangeParts = part.split('-')
    if (rangeParts.length === 1) {
      if (/^\d+$/.test(rangeParts[0].trim()) === false) {
        return false
      }
      continue
    }
    if (rangeParts.length !== 2) {
      return false
    }
    const startText = rangeParts[0].trim()
    const endText = rangeParts[1].trim()
    if (/^\d+$/.test(startText) === false || /^\d+$/.test(endText) === false) {
      return false
    }
    if (Number(startText) > Number(endText)) {
      return false
    }
  }
  return true
}

function isExperimentIdParam(name: string): boolean {
  return name === EXPERIMENT_ID_PARAM_NAME
}

function isAnalysisSection(name: string): boolean {
  return name === ANALYSIS_SECTION_TITLE
}

function isAnalysisMethodParam(name: string): name is AnalysisParamName {
  return ANALYSIS_PARAM_NAMES.some((paramName) => paramName === name)
}

function analysisInstrumentLabel(name: string): string {
  if (isAnalysisMethodParam(name) === false) {
    return name
  }
  return ANALYSIS_PARAM_CONFIG[name].label
}

function analysisMethodOptions(name: string, value: unknown): string[] {
  if (isAnalysisMethodParam(name) === false) {
    return []
  }
  const instrument = ANALYSIS_PARAM_CONFIG[name].instrument
  const options = [...methodOptions.value[instrument]]
  const currentValue = cellText(value)
  if (currentValue !== '' && options.includes(currentValue) === false) {
    options.unshift(currentValue)
  }
  return options
}

function analysisSampleSelector(name: string): string {
  if (isAnalysisMethodParam(name) === false) {
    return ''
  }
  return analysisSampleSelectors.value[name]
}

function setAnalysisSampleSelector(name: string, value: string | number) {
  if (isAnalysisMethodParam(name) === false) {
    return
  }
  analysisSampleSelectors.value[name] = String(value)
}

function setAnalysisMethodValue(item: { name: string; value: unknown }, value: unknown) {
  item.value = value ?? ''
  if (isAnalysisMethodParam(item.name) === false) {
    return
  }
  if (cellText(item.value) === '') {
    analysisSampleSelectors.value[item.name] = ''
  }
}

function syncAnalysisParamState(data: ReactionTemplate) {
  const selectors: Record<AnalysisParamName, string> = {
    GC_MS: '',
    UPLC_QTOF: '',
    HPLC: '',
  }
  for (const item of data.param_rows) {
    if (item.type !== 'parameter' || isAnalysisMethodParam(item.name) === false) {
      continue
    }
    const parsed = parseAnalysisMethodValue(item.value)
    item.value = parsed.method
    selectors[item.name] = parsed.selector
    data.params[item.name] = parsed.method
  }
  analysisSampleSelectors.value = selectors
}

function parseAnalysisMethodValue(value: unknown): { method: string; selector: string } {
  const text = cellText(value)
  if (text === '') {
    return {
      method: '',
      selector: '',
    }
  }
  const match = text.match(/^(.*)\(([^()]*)\)$/)
  if (match === null) {
    return {
      method: text,
      selector: '',
    }
  }
  return {
    method: match[1].trim(),
    selector: match[2].trim(),
  }
}

function experimentIdDisplayValue(value: unknown): string {
  const text = cellText(value)
  if (text === '') {
    return ''
  }
  return text
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value).trim()
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
  templateData.value.rows = buildTemplateRows(templateData.value.rows, width, count)
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

function fillTemplateTable(mode: FillMode) {
  if (spreadsheetRef.value === null) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  spreadsheetRef.value.fillSelectedRange(mode)
}

function clearTemplateSelection() {
  if (spreadsheetRef.value === null) {
    ElMessage.warning('表格尚未就绪')
    return
  }
  if (spreadsheetRef.value.clearSelectedRange() === true) {
    ElMessage.success('选定内容已清除')
  }
}

function clearAllTemplateContent() {
  if (templateData.value === null) {
    return
  }
  if (spreadsheetRef.value !== null) {
    const rows = spreadsheetRef.value.syncSourceData()
    updateTemplateRows(rows)
  }
  const width = templateData.value.headers.length
  templateData.value.rows = templateData.value.rows.map((_row, rowIndex) => {
    const nextRow: unknown[] = Array.from({ length: width }, () => '')
    nextRow[0] = rowIndex + 1
    return nextRow
  })
  ElMessage.success('所有内容已清除')
}

function addBatchInRow() {
  if (batchInData.value === null) {
    return
  }
  syncBatchInSpreadsheet()
  const width = batchInData.value.headers.length
  batchInData.value.rows.push(Array.from({ length: width }, () => ''))
  batchInSpreadsheetVersion.value += 1
}

function removeBatchInRow() {
  if (batchInData.value === null) {
    return
  }
  syncBatchInSpreadsheet()
  const rowIndex = selectedBatchInRow.value
  if (rowIndex === null || rowIndex < 0 || rowIndex >= batchInData.value.rows.length) {
    ElMessage.warning('请先选择要删除的上料行')
    return
  }
  batchInData.value.rows.splice(rowIndex, 1)
  selectedBatchInRow.value = null
  batchInSpreadsheetVersion.value += 1
}

function clearBatchInSelection() {
  if (batchInSpreadsheetRef.value === null) {
    ElMessage.warning('上料表格尚未就绪')
    return
  }
  if (batchInSpreadsheetRef.value.clearSelectedRange() === true) {
    ElMessage.success('选定内容已清除')
  }
}

function clearAllBatchInContent() {
  if (batchInData.value === null) {
    return
  }
  syncBatchInSpreadsheet()
  const width = batchInData.value.headers.length
  batchInData.value.rows = batchInData.value.rows.map(() => {
    return Array.from({ length: width }, () => '')
  })
  selectedBatchInRow.value = null
  batchInSpreadsheetVersion.value += 1
  ElMessage.success('所有上料内容已清除')
}

function updateTemplateRows(rows: SpreadsheetRow[]) {
  if (templateData.value === null) {
    return
  }
  const width = templateData.value.headers.length
  const rowCount = resolveTemplateRowCount(
    rows,
    templateData.value.rows.length,
    templateData.value.supported_experiment_counts,
  )
  templateData.value.rows = buildTemplateRows(rows, width, rowCount)
}

function updateBatchInRows(rows: SpreadsheetRow[]) {
  if (batchInData.value === null) {
    return
  }
  const width = batchInData.value.headers.length
  batchInData.value.rows = rows.map((row) => normalizeSpreadsheetRow(row, width))
}

function syncTemplateSpreadsheet() {
  if (spreadsheetRef.value === null) {
    return
  }
  const rows = spreadsheetRef.value.syncSourceData()
  updateTemplateRows(rows)
}

function syncBatchInSpreadsheet() {
  if (batchInSpreadsheetRef.value === null) {
    return
  }
  const rows = batchInSpreadsheetRef.value.syncSourceData()
  updateBatchInRows(rows)
}

function setTemplateData(data: ReactionTemplate, options: TemplateLoadOptions = {}) {
  const nextData = cloneReactionTemplate(data)
  if (options.keepExperimentId !== true) {
    clearExperimentId(nextData)
  }
  syncAnalysisParamState(nextData)
  normalizeTemplateDataRows(nextData)
  skipTemplatePersist = true
  templateData.value = nextData
  void nextTick(() => {
    skipTemplatePersist = false
  })
}

function setBatchInData(data: BatchInTemplate) {
  batchInData.value = cloneBatchInTemplate(data)
  batchInSpreadsheetVersion.value += 1
}

function readTemplateDraft(remoteTemplate: ReactionTemplate): ReactionTemplate | null {
  try {
    const rawDraft = localStorage.getItem(TASK_EDITOR_DRAFT_KEY)
    if (rawDraft === null) {
      return null
    }
    const draft = JSON.parse(rawDraft) as ReactionTemplate
    if (isCompatibleTemplateDraft(remoteTemplate, draft) === false) {
      return null
    }
    return draft
  } catch {
    return null
  }
}

function isCompatibleTemplateDraft(remoteTemplate: ReactionTemplate, draft: ReactionTemplate): boolean {
  if (Array.isArray(draft.headers) === false || Array.isArray(draft.rows) === false) {
    return false
  }
  if (Array.isArray(draft.param_rows) === false) {
    return false
  }
  return (
    isCompatibleTemplateHeaders(remoteTemplate.headers, draft.headers) === true &&
    draft.param_rows.map((item) => item.name).join('|') ===
      remoteTemplate.param_rows.map((item) => item.name).join('|')
  )
}

function isCompatibleTemplateHeaders(remoteHeaders: string[], draftHeaders: string[]): boolean {
  if (remoteHeaders.length === 0 || draftHeaders.length === 0) {
    return false
  }
  const sharedLength = Math.min(remoteHeaders.length, draftHeaders.length)
  for (let index = 0; index < sharedLength; index += 1) {
    if (remoteHeaders[index] !== draftHeaders[index]) {
      return false
    }
  }
  const extraHeaders = draftHeaders.length > remoteHeaders.length
    ? draftHeaders.slice(remoteHeaders.length)
    : remoteHeaders.slice(draftHeaders.length)
  return isTrailingReagentPairHeaders(extraHeaders)
}

function isTrailingReagentPairHeaders(headers: string[]): boolean {
  if (headers.length === 0) {
    return true
  }
  if (headers.length % 2 !== 0) {
    return false
  }
  for (let index = 0; index < headers.length; index += 2) {
    if (headers[index] !== '试剂' || headers[index + 1] !== '试剂量') {
      return false
    }
  }
  return true
}

function persistTemplateDraft() {
  if (templateData.value === null || skipTemplatePersist === true) {
    return
  }
  const draft = cloneReactionTemplate(templateData.value)
  serializeAnalysisParams(draft)
  clearExperimentId(draft)
  localStorage.setItem(TASK_EDITOR_DRAFT_KEY, JSON.stringify(draft))
}

function clearTemplateDraft() {
  localStorage.removeItem(TASK_EDITOR_DRAFT_KEY)
}

function normalizeSpreadsheetRow(row: SpreadsheetRow, width: number): unknown[] {
  const values = Array.isArray(row) === true ? [...row] : []
  while (values.length < width) {
    values.push('')
  }
  return values.slice(0, width)
}

function normalizeTemplateDataRows(data: ReactionTemplate) {
  const width = data.headers.length
  const rowCount = resolveTemplateRowCount(
    data.rows,
    data.rows.length,
    data.supported_experiment_counts,
  )
  data.rows = buildTemplateRows(data.rows, width, rowCount)
}

function buildTemplateRows(rows: SpreadsheetRow[], width: number, count: number): unknown[][] {
  const nextRows: unknown[][] = []
  for (let index = 0; index < count; index += 1) {
    const nextRow = normalizeSpreadsheetRow(rows[index], width)
    nextRow[0] = index + 1
    nextRows.push(nextRow)
  }
  return nextRows
}

function resolveTemplateRowCount(
  rows: SpreadsheetRow[],
  currentCount: number,
  supportedCounts: number[],
): number {
  const supported = normalizeSupportedExperimentCounts(supportedCounts)
  if (supported.includes(currentCount) === true) {
    return currentCount
  }

  const meaningfulCount = countMeaningfulTemplateRows(rows)
  if (meaningfulCount <= 0) {
    return supported[0] || 12
  }

  const exactCount = supported.find((count) => count === meaningfulCount)
  if (exactCount !== undefined) {
    return exactCount
  }

  const nextCount = supported.find((count) => count >= meaningfulCount)
  if (nextCount !== undefined) {
    return nextCount
  }

  return supported[supported.length - 1] || meaningfulCount
}

function normalizeSupportedExperimentCounts(counts: number[]): number[] {
  const fallbackCounts = [12, 24, 36, 48]
  const sourceCounts = Array.isArray(counts) === true && counts.length > 0 ? counts : fallbackCounts
  return [...new Set(sourceCounts)]
    .filter((count) => Number.isFinite(count) === true && count > 0)
    .sort((left, right) => left - right)
}

function countMeaningfulTemplateRows(rows: SpreadsheetRow[]): number {
  let lastMeaningfulIndex = -1
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex]
    const values = Array.isArray(row) === true ? row : []
    for (let colIndex = 1; colIndex < values.length; colIndex += 1) {
      if (cellText(values[colIndex]) === '') {
        continue
      }
      lastMeaningfulIndex = rowIndex
      break
    }
  }
  return lastMeaningfulIndex + 1
}

onActivated(() => {
  loadTemplate()
  loadBatchInTemplate()
  loadAnalysisMethods()
})

watch(
  templateData,
  () => {
    persistTemplateDraft()
  },
  { deep: true },
)

watch(
  analysisSampleSelectors,
  () => {
    persistTemplateDraft()
  },
  { deep: true },
)
</script>

<template>
  <div class="view-stack" v-loading="loading">
    <section class="panel editor-settings-panel">
      <div class="panel-title">
        <h2>实验设定</h2>
        <div class="button-row editor-button-row">
          <el-button size="small" :icon="Refresh" @click="reloadEditorData">重载</el-button>
          <el-button size="small" type="primary" :icon="DocumentChecked" @click="saveTemplate">保存</el-button>
          <el-button size="small" type="success" :icon="Upload" @click="submitTemplate">上传任务</el-button>
        </div>
      </div>

      <div v-if="templateData !== null" class="settings-grid">
        <div
          v-for="(columnGroups, columnIndex) in settingsColumns"
          :key="columnIndex"
          :class="['settings-column', columnIndex === 0 ? 'settings-column-left' : 'settings-column-right']"
        >
          <section
            v-for="group in columnGroups"
            :key="group.title"
            class="settings-group"
          >
            <div class="settings-section">{{ group.title }}</div>
            <div class="settings-group-fields">
              <el-form-item
                v-for="item in group.items"
                :key="item.name"
                :label="item.name"
                class="settings-item"
              >
                <el-input
                  v-if="isExperimentIdParam(item.name)"
                  :model-value="experimentIdDisplayValue(item.value)"
                  disabled
                  placeholder="提交后自动回写"
                />
                <el-select v-else-if="isYesNoParam(item.name)" v-model="item.value" style="width: 100%">
                  <el-option label="是" value="是" />
                  <el-option label="否" value="否" />
                </el-select>
                <el-select v-else-if="isReactorParam(item.name)" v-model="item.value" style="width: 100%">
                  <el-option label="heat" value="heat" />
                </el-select>
                <el-input v-else v-model="item.value" />
              </el-form-item>
            </div>
          </section>
        </div>

        <section v-if="analysisSettingGroup !== null" class="settings-group analysis-settings-group">
          <div class="settings-section">{{ analysisSettingGroup.title }}</div>
          <div class="analysis-method-grid">
            <el-form-item
              v-for="analysisItem in analysisSettingGroup.items"
              :key="analysisItem.name"
              :label="analysisInstrumentLabel(analysisItem.name)"
              class="settings-item analysis-method-item"
            >
              <div class="analysis-method-row">
                <el-select
                  :model-value="analysisItem.value"
                  :loading="methodsLoading"
                  clearable
                  filterable
                  placeholder="选择方法"
                  style="width: 100%"
                  @update:model-value="setAnalysisMethodValue(analysisItem, $event)"
                >
                  <el-option
                    v-for="methodName in analysisMethodOptions(analysisItem.name, analysisItem.value)"
                    :key="methodName"
                    :label="methodName"
                    :value="methodName"
                  />
                </el-select>
                <el-input
                  :model-value="analysisSampleSelector(analysisItem.name)"
                  :disabled="cellText(analysisItem.value) === ''"
                  placeholder="实验编号"
                  @update:model-value="setAnalysisSampleSelector(analysisItem.name, $event)"
                />
              </div>
            </el-form-item>
          </div>
        </section>
      </div>
    </section>

    <section class="panel editor-table-panel">
      <el-tabs v-model="activeTableTab" type="card" class="editor-table-tabs">
        <el-tab-pane label="试剂表格" name="reagent">
          <div class="button-row table-button-row">
            <el-select
              :model-value="experimentCount"
              size="small"
              class="experiment-count-select"
              @change="setExperimentCount"
            >
              <el-option
                v-for="count in templateData?.supported_experiment_counts || [12, 24, 36, 48]"
                :key="count"
                :label="String(count) + ' 个实验'"
                :value="count"
              />
            </el-select>
            <el-button :icon="Plus" @click="addReagentPair">试剂列</el-button>
            <el-button :icon="Minus" @click="removeReagentPair">试剂列</el-button>
            <el-button :icon="Delete" @click="clearTemplateSelection">清除内容</el-button>
            <el-button :icon="DeleteFilled" @click="clearAllTemplateContent">清除所有内容</el-button>
            <el-button :icon="TrendCharts" @click="fillTemplateTable('increment')">递增填充</el-button>
            <el-button :icon="CopyDocument" @click="fillTemplateTable('copy')">复制填充</el-button>
            <el-checkbox v-model="autoGenerateBatchFile" class="resource-check-option">自动修改上料文件</el-checkbox>
            <el-button type="warning" :icon="CircleCheck" @click="runResourceCheck">物料核算</el-button>
            <el-button type="primary" :icon="DocumentChecked" @click="saveReactionTemplateOnly">保存</el-button>
          </div>

          <div v-if="templateData !== null" class="spreadsheet-wrap">
            <EditableSpreadsheet
              :key="spreadsheetKey"
              ref="spreadsheetRef"
              :model-value="templateData.rows"
              :col-headers="templateData.headers"
              :columns="spreadsheetColumns"
              :height="520"
              @update:model-value="updateTemplateRows"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="上料表格" name="batchIn">
          <div class="button-row table-button-row">
            <el-button :icon="Plus" @click="addBatchInRow">新增行</el-button>
            <el-button :icon="Delete" @click="removeBatchInRow">删除行</el-button>
            <el-button :icon="Delete" @click="clearBatchInSelection">清除内容</el-button>
            <el-button :icon="DeleteFilled" @click="clearAllBatchInContent">清除所有内容</el-button>
            <el-button type="warning" :icon="Tickets" @click="printReagentLabels">打印试剂标签</el-button>
            <el-button type="success" :icon="Printer" @click="printBatchInTable">打印上料表格</el-button>
            <el-button type="primary" :icon="DocumentChecked" @click="saveBatchInTemplateOnly">保存</el-button>
          </div>

          <div v-loading="batchInLoading" class="batch-in-tab-body">
            <div v-if="batchInData !== null" class="spreadsheet-wrap">
              <EditableSpreadsheet
                :key="batchInSpreadsheetKey"
                ref="batchInSpreadsheetRef"
                :model-value="batchInData.rows"
                :col-headers="batchInData.headers"
                :columns="batchInColumns"
                :height="520"
                @update:model-value="updateBatchInRows"
                @selected-row="selectedBatchInRow = $event"
              />
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <JobPanel :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.editor-settings-panel {
  position: relative;
  z-index: 2;
  padding: 12px 14px;
}

.editor-settings-panel :deep(.panel-title),
.editor-settings-panel .panel-title {
  margin-bottom: 10px;
}

.editor-button-row {
  gap: 6px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  align-items: start;
}

.settings-column {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.settings-group {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.settings-section {
  min-height: 30px;
  padding: 6px 10px;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #eef4fb;
}

.settings-group-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
  align-items: start;
  min-width: 0;
  padding-left: 10px;
}

.settings-column-right .settings-group-fields {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.settings-item {
  margin-bottom: 0;
}

.settings-item :deep(.el-form-item__label) {
  min-height: 24px;
  padding-bottom: 4px;
  line-height: 24px;
}

.settings-item :deep(.el-form-item__content) {
  line-height: 28px;
}

.settings-item :deep(.el-input__wrapper),
.settings-item :deep(.el-select__wrapper) {
  min-height: 30px;
}

.analysis-settings-group {
  grid-column: 1 / -1;
}

.analysis-method-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 12px;
  align-items: start;
  min-width: 0;
  padding-left: 10px;
}

.analysis-method-item {
  min-width: 0;
}

.analysis-method-item :deep(.el-form-item__label) {
  align-items: center;
  min-height: 30px;
  padding-bottom: 0;
  line-height: 30px;
}

.analysis-method-item :deep(.el-form-item__content) {
  align-items: center;
}

.analysis-method-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 96px;
  gap: 6px;
  width: 100%;
}

.editor-table-panel {
  min-width: 0;
}

.editor-table-tabs {
  width: 100%;
}

.editor-table-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.editor-table-tabs :deep(.el-tabs__content) {
  min-width: 0;
  overflow: visible;
}

.table-button-row {
  justify-content: flex-end;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 2px 0;
}

.table-button-row :deep(.el-button) {
  margin-left: 0;
}

.experiment-count-select {
  width: 116px;
}

.resource-check-option {
  margin-left: 14px;
  margin-right: 0;
  min-height: 32px;
}

.batch-in-tab-body {
  min-height: 520px;
}

.spreadsheet-wrap {
  width: 100%;
  min-height: 360px;
}

@media (max-width: 1100px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .settings-column-right .settings-group-fields,
  .analysis-method-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .settings-column-right .settings-group-fields,
  .analysis-method-grid,
  .settings-group-fields {
    grid-template-columns: 1fr;
  }

  .analysis-method-row {
    grid-template-columns: minmax(150px, 1fr) 88px;
  }
}
</style>
