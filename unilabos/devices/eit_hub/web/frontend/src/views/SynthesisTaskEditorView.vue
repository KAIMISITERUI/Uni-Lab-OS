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
  Search,
  Tickets,
  TrendCharts,
  Upload,
} from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type BatchInTemplate,
  type GcMsYieldConfig,
  type GcMsYieldProduct,
  type JobState,
  type ParamRow,
  type ReactionTemplateHistoryItem,
  type ReactionTemplate,
  checkResource,
  fetchBatchInTemplate,
  fetchHistoricalReactionTemplate,
  fetchReactionTemplate,
  fetchReactionTemplateHistory,
  printBatchInReagentLabels,
  printBatchInTemplate,
  saveBatchInTemplate,
  saveReactionTemplate,
  submitReactionTemplate,
} from '../api/synthesis'
import { getChemicalBySubstance, listChemicals, type ChemicalRow } from '../api/chemicals'
import {
  fetchAnalysisMethods,
  type AnalysisInstrumentKey,
  type AnalysisMethodsRow,
} from '../api/analysis'
import { getErrorMessage } from '../api/http'
import { renderSmilesToSvg } from '../composables/useRDKit'
import EditableSpreadsheet from '../components/EditableSpreadsheet.vue'

type SpreadsheetRow = Record<string, unknown> | unknown[]
type FillMode = 'increment' | 'copy'
type EditorTab = 'settings' | 'analysis'
type SettingsTableTab = 'reagent' | 'batchIn'
type TemplateLoadOptions = {
  keepExperimentId?: boolean
}
type AnalysisParamName = 'GC_MS' | 'UPLC_QTOF' | 'HPLC'
type YieldMethod = 'ECN' | '标准曲线' | '响应因子'
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
const HISTORY_PAGE_SIZE = 10
const EXPERIMENT_ID_PARAM_NAME = '实验ID'
const INTERNAL_STANDARD_PARAM_NAME = '内标种类'
const ANALYSIS_SECTION_TITLE = '分析方法设定'
const LEFT_SETTING_GROUP_TITLES = ['实验设定', '反应设定', '称量设定']
const ANALYSIS_PARAM_NAMES: AnalysisParamName[] = ['GC_MS', 'UPLC_QTOF', 'HPLC']
const GC_PRODUCT_FIELD_ORDER: Array<keyof GcMsYieldProduct> = [
  'applicable_experiments',
  'product_name',
  'equivalent',
  'smiles',
  'expected_rt',
]
const GC_PRODUCT_HEADERS = ['适用实验', '目标产物名称', '当量(eq)', 'SMILES', '预期RT(min)', '产物结构式']
const YIELD_METHOD_OPTIONS: YieldMethod[] = ['ECN', '标准曲线', '响应因子']
const GC_PRODUCT_STRUCTURE_WIDTH = 180
const GC_PRODUCT_STRUCTURE_HEIGHT = 72
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
const historyLoading = ref(false)
const historyDialogVisible = ref(false)
const loadingHistoryTaskId = ref<number | null>(null)
const historyQuery = ref('')
const historyPage = ref(1)
const historyTotal = ref(0)
const methodsLoading = ref(false)
const internalStandardLoading = ref(false)
const spreadsheetRef = ref<EditableSpreadsheetRef | null>(null)
const batchInSpreadsheetRef = ref<EditableSpreadsheetRef | null>(null)
const gcProductSpreadsheetRef = ref<EditableSpreadsheetRef | null>(null)
const autoGenerateBatchFile = ref(true)
const refreshBatchInAfterResourceCheck = ref(false)
const activeEditorTab = ref<EditorTab>('settings')
const activeSettingsTableTab = ref<SettingsTableTab>('reagent')
const batchInSpreadsheetVersion = ref(0)
const gcProductSpreadsheetVersion = ref(0)
const selectedBatchInRow = ref<number | null>(null)
const selectedGcProductRow = ref<number | null>(null)
const internalStandardSmilesError = ref('')
const methodOptions = ref<Record<AnalysisInstrumentKey, string[]>>({
  gc_ms: [],
  uplc_qtof: [],
  hplc: [],
})
const historyItems = ref<ReactionTemplateHistoryItem[]>([])
const analysisSampleSelectors = ref<Record<AnalysisParamName, string>>({
  GC_MS: '',
  UPLC_QTOF: '',
  HPLC: '',
})
let skipTemplatePersist = false
let internalStandardQuerySeq = 0
let internalStandardTimer: ReturnType<typeof setTimeout> | null = null
let suppressNextInternalStandardAutofill = false
const gcProductStructureSvgCache = new Map<string, string | null>()
const gcProductStructurePendingCache = new Set<string>()

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

const gcMsYield = computed<GcMsYieldConfig | null>(() => {
  return templateData.value?.gc_ms_yield ?? null
})

const currentYieldMethod = computed<YieldMethod>(() => {
  if (gcMsYield.value === null) {
    return 'ECN'
  }
  return normalizeYieldMethod(gcMsYield.value.yield_method)
})

const showCurveFields = computed(() => currentYieldMethod.value === '标准曲线')
const showResponseFactorField = computed(() => currentYieldMethod.value === '响应因子')

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

const gcProductColumns = computed<Array<Record<string, unknown>>>(() => {
  return [
    { data: 'applicable_experiments', type: 'text', width: 140 },
    { data: 'product_name', type: 'text', width: 220 },
    { data: 'equivalent', type: 'text', width: 120 },
    { data: 'smiles', type: 'text', width: 260 },
    { data: 'expected_rt', type: 'text', width: 140 },
    {
      data: 'structure_preview',
      readOnly: true,
      width: GC_PRODUCT_STRUCTURE_WIDTH,
      renderer: gcProductStructureRenderer,
    },
  ]
})

const gcProductSpreadsheetKey = computed(() => {
  const rowCount = gcMsYield.value?.products.length ?? 0
  return `gc-products-${rowCount}-${gcProductSpreadsheetVersion.value}`
})

const gcProductSpreadsheetRows = computed(() => {
  if (gcMsYield.value === null) {
    return []
  }
  return gcMsYield.value.products.map((row) => {
    const normalizedRow = normalizeGcMsYieldProduct(row)
    return {
      ...normalizedRow,
      structure_preview: cellText(normalizedRow.smiles),
    }
  })
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

async function openHistoryDialog() {
  historyDialogVisible.value = true
  historyPage.value = 1
  await loadHistoryList(1)
}

async function loadHistoryList(page = historyPage.value) {
  historyLoading.value = true
  try {
    const response = await fetchReactionTemplateHistory({
      q: historyQuery.value.trim() !== '' ? historyQuery.value.trim() : undefined,
      page,
      page_size: HISTORY_PAGE_SIZE,
    })
    historyItems.value = response.items
    historyTotal.value = response.total
    historyPage.value = response.page
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    historyLoading.value = false
  }
}

async function searchHistoryList() {
  historyPage.value = 1
  await loadHistoryList(1)
}

async function onHistoryPageChange(page: number) {
  historyPage.value = page
  await loadHistoryList(page)
}

async function loadHistoricalTemplate(taskId: number) {
  loadingHistoryTaskId.value = taskId
  try {
    const template = await fetchHistoricalReactionTemplate(taskId)
    if (template.has_gc_ms_yield_sheet !== true) {
      template.gc_ms_yield = buildEmptyGcMsYield()
      suppressNextInternalStandardAutofill = true
    }
    setTemplateData(template)
    activeEditorTab.value = 'settings'
    historyDialogVisible.value = false
    ElMessage.success(`已载入历史任务 ${taskId} 的数据`)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loadingHistoryTaskId.value = null
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

function chemicalNameAutocompleteSource(
  query: string,
  process: (choices: Array<{ value: string }>) => void,
) {
  void loadChemicalNames(query).then((choices) => {
    process(
      choices.map((choice) => {
        return { value: choice }
      }),
    )
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

function gcProductStructureRenderer(
  instance: any,
  td: HTMLTableCellElement,
  row: number,
  _col: number,
  _prop: unknown,
  value: unknown,
) {
  const sourceRow = instance.getSourceDataAtRow(row) as Record<string, unknown> | undefined
  const smiles = cellText(sourceRow?.smiles ?? value)
  td.innerHTML = ''
  td.style.padding = '4px'
  td.style.verticalAlign = 'middle'
  td.style.textAlign = 'center'

  if (smiles === '') {
    td.innerHTML = `<div style="color:#a8abb2;font-size:12px;line-height:${GC_PRODUCT_STRUCTURE_HEIGHT}px;">暂无结构</div>`
    return td
  }

  const cacheKey = `${smiles}|${GC_PRODUCT_STRUCTURE_WIDTH}x${GC_PRODUCT_STRUCTURE_HEIGHT}`
  const cachedSvg = gcProductStructureSvgCache.get(cacheKey)
  if (cachedSvg !== undefined) {
    if (cachedSvg === null) {
      td.innerHTML = `<div style="color:#f56c6c;font-size:12px;line-height:${GC_PRODUCT_STRUCTURE_HEIGHT}px;">结构解析失败</div>`
      return td
    }
    td.innerHTML = buildGcProductStructureHtml(cachedSvg)
    return td
  }

  td.innerHTML = `<div style="color:#909399;font-size:12px;line-height:${GC_PRODUCT_STRUCTURE_HEIGHT}px;">加载中...</div>`
  if (gcProductStructurePendingCache.has(cacheKey) === true) {
    return td
  }

  gcProductStructurePendingCache.add(cacheKey)
  void renderSmilesToSvg(smiles, GC_PRODUCT_STRUCTURE_WIDTH - 16, GC_PRODUCT_STRUCTURE_HEIGHT - 12)
    .then((svg) => {
      gcProductStructureSvgCache.set(cacheKey, svg)
    })
    .catch(() => {
      gcProductStructureSvgCache.set(cacheKey, null)
    })
    .finally(() => {
      gcProductStructurePendingCache.delete(cacheKey)
      instance.render()
    })
  return td
}

function buildGcProductStructureHtml(svgContent: string): string {
  return [
    `<div style="display:flex;align-items:center;justify-content:center;height:${GC_PRODUCT_STRUCTURE_HEIGHT}px;">`,
    '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;overflow:hidden;border:1px solid var(--el-border-color-lighter, #ebeef5);border-radius:4px;background:#fff;">',
    svgContent,
    '</div>',
    '</div>',
  ].join('')
}

async function refreshInternalStandardSmiles(substanceName: string) {
  if (templateData.value === null) {
    return
  }
  const queryText = substanceName.trim()
  internalStandardQuerySeq += 1
  const currentQuerySeq = internalStandardQuerySeq

  if (queryText === '') {
    templateData.value.gc_ms_yield.internal_standard_smiles = ''
    internalStandardSmilesError.value = ''
    internalStandardLoading.value = false
    return
  }

  internalStandardLoading.value = true
  try {
    const row = await getChemicalBySubstance(queryText)
    if (currentQuerySeq !== internalStandardQuerySeq || templateData.value === null) {
      return
    }
    const smiles = cellText(row.smiles)
    if (smiles === '') {
      templateData.value.gc_ms_yield.internal_standard_smiles = ''
      internalStandardSmilesError.value = `化学品库中的内标“${queryText}”缺少 SMILES`
      return
    }
    templateData.value.gc_ms_yield.internal_standard_smiles = smiles
    internalStandardSmilesError.value = ''
  } catch {
    if (currentQuerySeq !== internalStandardQuerySeq || templateData.value === null) {
      return
    }
    templateData.value.gc_ms_yield.internal_standard_smiles = ''
    internalStandardSmilesError.value = `未在化学品库中找到内标“${queryText}”的可用 SMILES`
  } finally {
    if (currentQuerySeq === internalStandardQuerySeq) {
      internalStandardLoading.value = false
    }
  }
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
    ElMessage.success('任务模板和上料文件已保存')
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
    ElMessage.success('任务模板已保存')
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
  syncGcProductSpreadsheet()
  if (validateAnalysisParams() === false) {
    return null
  }
  if (validateGcMsYield() === false) {
    return null
  }
  const payload = cloneReactionTemplate(templateData.value)
  serializeAnalysisParams(payload)
  payload.gc_ms_yield = buildGcMsYieldPayload(payload.gc_ms_yield)
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

function cloneGcMsYield(data: GcMsYieldConfig): GcMsYieldConfig {
  return JSON.parse(JSON.stringify(data)) as GcMsYieldConfig
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

function validateGcMsYield(): boolean {
  if (gcMsYield.value === null) {
    return false
  }
  const internalStandardName = currentInternalStandardName()
  if (internalStandardName === '') {
    ElMessage.error('请先在实验设定中填写内标种类')
    return false
  }
  if (internalStandardLoading.value === true) {
    ElMessage.warning('正在从化学品库获取内标SMILES, 请稍后再试')
    return false
  }
  if (internalStandardSmilesError.value !== '') {
    ElMessage.error(internalStandardSmilesError.value)
    return false
  }
  if (cellText(gcMsYield.value.internal_standard_smiles) === '') {
    ElMessage.error('未获取到内标SMILES, 请检查化学品库中的内标配置')
    return false
  }

  const method = normalizeYieldMethod(gcMsYield.value.yield_method)
  if (method === '标准曲线' && cellText(gcMsYield.value.curve_slope) === '') {
    ElMessage.error('选择标准曲线法时必须填写标准曲线斜率')
    return false
  }
  if (method === '响应因子' && cellText(gcMsYield.value.response_factor) === '') {
    ElMessage.error('选择响应因子法时必须填写响应因子')
    return false
  }

  const productError = validateGcProductRows(gcMsYield.value.products)
  if (productError !== '') {
    ElMessage.error(productError)
    return false
  }
  return true
}

function validateGcProductRows(products: GcMsYieldProduct[]): string {
  for (let index = 0; index < products.length; index += 1) {
    const row = normalizeGcMsYieldProduct(products[index])
    const hasAnyValue = GC_PRODUCT_FIELD_ORDER.some((fieldName) => cellText(row[fieldName]) !== '')
    if (hasAnyValue === false) {
      continue
    }
    if (cellText(row.product_name) === '') {
      return `GC-MS 目标产物第 ${index + 1} 行缺少目标产物名称`
    }
    if (cellText(row.smiles) === '') {
      return `GC-MS 目标产物第 ${index + 1} 行缺少 SMILES`
    }
  }
  return ''
}

function buildGcMsYieldPayload(rawConfig: GcMsYieldConfig): GcMsYieldConfig {
  const payload = cloneGcMsYield(rawConfig)
  payload.internal_standard_smiles = cellText(payload.internal_standard_smiles)
  payload.yield_method = normalizeYieldMethod(payload.yield_method)
  payload.products = payload.products
    .map((row) => normalizeGcMsYieldProduct(row))
    .filter((row) => isGcMsYieldProductMeaningful(row))
  clearYieldMethodFields(payload)
  return payload
}

function isGcMsYieldProductMeaningful(row: GcMsYieldProduct): boolean {
  return GC_PRODUCT_FIELD_ORDER.some((fieldName) => cellText(row[fieldName]) !== '')
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

function setYieldMethodValue(value: unknown) {
  if (gcMsYield.value === null) {
    return
  }
  gcMsYield.value.yield_method = normalizeYieldMethod(value)
  clearYieldMethodFields(gcMsYield.value)
}

function clearYieldMethodFields(config: GcMsYieldConfig) {
  const method = normalizeYieldMethod(config.yield_method)
  if (method === 'ECN') {
    config.curve_slope = ''
    config.curve_intercept = ''
    config.response_factor = ''
    return
  }
  if (method === '标准曲线') {
    config.response_factor = ''
    return
  }
  config.curve_slope = ''
  config.curve_intercept = ''
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
  return cellText(value)
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value).trim()
}

function normalizeYieldMethod(value: unknown): YieldMethod {
  const text = cellText(value)
  const upperText = text.toUpperCase()
  if (text === '' || upperText === 'ECN') {
    return 'ECN'
  }
  if (text === '标准曲线' || upperText === 'CALIBRATION' || upperText === 'CURVE') {
    return '标准曲线'
  }
  if (text === '响应因子' || upperText === 'RF' || upperText === 'RESPONSE_FACTOR') {
    return '响应因子'
  }
  return 'ECN'
}

function buildEmptyGcMsYield(): GcMsYieldConfig {
  return {
    internal_standard_smiles: '',
    internal_standard_expected_rt: '',
    yield_method: 'ECN',
    curve_slope: '',
    curve_intercept: '',
    response_factor: '',
    products: [],
  }
}

function buildEmptyGcMsYieldProduct(): GcMsYieldProduct {
  return {
    applicable_experiments: '',
    product_name: '',
    equivalent: '',
    smiles: '',
    expected_rt: '',
  }
}

function normalizeGcMsYieldData(data: ReactionTemplate) {
  data.gc_ms_yield = normalizeGcMsYield(data.gc_ms_yield)
}

function normalizeGcMsYield(rawConfig: unknown): GcMsYieldConfig {
  const source =
    typeof rawConfig === 'object' && rawConfig !== null
      ? (rawConfig as Partial<GcMsYieldConfig>)
      : ({} as Partial<GcMsYieldConfig>)
  const config: GcMsYieldConfig = {
    internal_standard_smiles: source.internal_standard_smiles ?? '',
    internal_standard_expected_rt: source.internal_standard_expected_rt ?? '',
    yield_method: normalizeYieldMethod(source.yield_method),
    curve_slope: source.curve_slope ?? '',
    curve_intercept: source.curve_intercept ?? '',
    response_factor: source.response_factor ?? '',
    products: normalizeGcMsYieldProducts(source.products),
  }
  clearYieldMethodFields(config)
  return config
}

function normalizeGcMsYieldProducts(rawProducts: unknown): GcMsYieldProduct[] {
  if (Array.isArray(rawProducts) === false) {
    return []
  }
  return rawProducts.map((row) => normalizeGcMsYieldProduct(row))
}

function normalizeGcMsYieldProduct(row: unknown): GcMsYieldProduct {
  if (Array.isArray(row) === true) {
    return {
      applicable_experiments: row[0] ?? '',
      product_name: row[1] ?? '',
      equivalent: row[2] ?? '',
      smiles: row[3] ?? '',
      expected_rt: row[4] ?? '',
    }
  }
  if (typeof row === 'object' && row !== null) {
    const source = row as Partial<GcMsYieldProduct>
    return {
      applicable_experiments: source.applicable_experiments ?? '',
      product_name: source.product_name ?? '',
      equivalent: source.equivalent ?? '',
      smiles: source.smiles ?? '',
      expected_rt: source.expected_rt ?? '',
    }
  }
  return buildEmptyGcMsYieldProduct()
}

function isYesNoParam(name: string): boolean {
  return ['等待目标温度', '固定加料顺序', '自动加磁子'].includes(name)
}

function isReactorParam(name: string): boolean {
  return name === '反应器类型'
}

function isChemicalAutocompleteParam(name: string): boolean {
  return name === INTERNAL_STANDARD_PARAM_NAME
}

function isReagentNameColumn(header: string, index: number): boolean {
  if (index === 0) {
    return false
  }
  return header.includes('试剂') && header.includes('量') === false
}

function currentInternalStandardName(): string {
  if (templateData.value === null) {
    return ''
  }
  const paramRow = templateData.value.param_rows.find((item) => {
    return item.type === 'parameter' && item.name === INTERNAL_STANDARD_PARAM_NAME
  })
  if (paramRow !== undefined) {
    return cellText(paramRow.value)
  }
  return cellText(templateData.value.params[INTERNAL_STANDARD_PARAM_NAME])
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

function addGcProductRow() {
  if (gcMsYield.value === null) {
    return
  }
  syncGcProductSpreadsheet()
  gcMsYield.value.products.push(buildEmptyGcMsYieldProduct())
  gcProductSpreadsheetVersion.value += 1
}

function removeGcProductRow() {
  if (gcMsYield.value === null) {
    return
  }
  syncGcProductSpreadsheet()
  const rowIndex = selectedGcProductRow.value
  if (rowIndex === null || rowIndex < 0 || rowIndex >= gcMsYield.value.products.length) {
    ElMessage.warning('请先选择要删除的目标产物行')
    return
  }
  gcMsYield.value.products.splice(rowIndex, 1)
  selectedGcProductRow.value = null
  gcProductSpreadsheetVersion.value += 1
}

function clearGcProductSelection() {
  if (gcProductSpreadsheetRef.value === null) {
    ElMessage.warning('目标产物表格尚未就绪')
    return
  }
  if (gcProductSpreadsheetRef.value.clearSelectedRange() === true) {
    ElMessage.success('选定内容已清除')
  }
}

function clearAllGcProductContent() {
  if (gcMsYield.value === null) {
    return
  }
  gcMsYield.value.products = []
  selectedGcProductRow.value = null
  gcProductSpreadsheetVersion.value += 1
  ElMessage.success('所有目标产物已清除')
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

function updateGcProductRows(rows: SpreadsheetRow[]) {
  if (templateData.value === null) {
    return
  }
  templateData.value.gc_ms_yield.products = rows.map((row) => normalizeGcMsYieldProduct(row))
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

function syncGcProductSpreadsheet() {
  if (gcProductSpreadsheetRef.value === null) {
    return
  }
  const rows = gcProductSpreadsheetRef.value.syncSourceData()
  updateGcProductRows(rows)
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
  normalizeGcMsYieldData(nextData)
  internalStandardSmilesError.value = ''
  gcProductSpreadsheetVersion.value += 1
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
  if (isValidGcMsYieldDraft(draft.gc_ms_yield) === false) {
    return false
  }
  return (
    isCompatibleTemplateHeaders(remoteTemplate.headers, draft.headers) === true &&
    draft.param_rows.map((item) => item.name).join('|') ===
      remoteTemplate.param_rows.map((item) => item.name).join('|')
  )
}

function isValidGcMsYieldDraft(rawConfig: unknown): boolean {
  if (typeof rawConfig !== 'object' || rawConfig === null) {
    return false
  }
  const source = rawConfig as Partial<GcMsYieldConfig>
  return Array.isArray(source.products) === true
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
  const extraHeaders =
    draftHeaders.length > remoteHeaders.length
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

watch(
  () => currentInternalStandardName(),
  (value) => {
    if (suppressNextInternalStandardAutofill === true) {
      suppressNextInternalStandardAutofill = false
      return
    }
    if (internalStandardTimer !== null) {
      clearTimeout(internalStandardTimer)
    }
    internalStandardTimer = setTimeout(() => {
      void refreshInternalStandardSmiles(value)
    }, 300)
  },
  { immediate: true },
)
</script>

<template>
  <div class="view-stack" v-loading="loading">
    <section class="panel editor-panel">
      <div class="panel-title">
        <h2>任务编辑</h2>
        <div class="button-row editor-button-row">
          <el-button size="small" :icon="Refresh" @click="reloadEditorData">重载</el-button>
          <el-button size="small" :icon="CopyDocument" class="history-load-button" @click="openHistoryDialog">
            载入历史
          </el-button>
          <el-button size="small" type="primary" :icon="DocumentChecked" @click="saveTemplate">
            保存
          </el-button>
          <el-button size="small" type="success" :icon="Upload" @click="submitTemplate">
            上传任务
          </el-button>
        </div>
      </div>

      <el-tabs v-model="activeEditorTab" type="card" class="editor-tabs">
        <el-tab-pane label="实验设定" name="settings">
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
                    <el-autocomplete
                      v-else-if="isChemicalAutocompleteParam(item.name)"
                      :model-value="cellText(item.value)"
                      :fetch-suggestions="chemicalNameAutocompleteSource"
                      clearable
                      placeholder="输入以搜索化学品库"
                      style="width: 100%"
                      @update:model-value="item.value = $event"
                    />
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

          <section class="editor-table-panel">
            <el-tabs v-model="activeSettingsTableTab" type="card" class="editor-table-tabs">
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
        </el-tab-pane>

        <el-tab-pane label="数据分析" name="analysis">
          <div v-if="gcMsYield !== null" class="analysis-tab-body">
            <section class="analysis-block">
              <div class="settings-section">GC-MS 数据分析</div>
              <div class="yield-form-grid">
                <el-form-item label="内标SMILES" class="settings-item">
                  <el-input
                    :model-value="gcMsYield.internal_standard_smiles"
                    readonly
                    :placeholder="internalStandardLoading ? '正在从化学品库获取' : '根据内标种类自动获取'"
                  />
                </el-form-item>
                <el-form-item label="内标预期RT(min)" class="settings-item">
                  <el-input v-model="gcMsYield.internal_standard_expected_rt" />
                </el-form-item>
                <el-form-item label="产率计算方法" class="settings-item">
                  <el-select
                    :model-value="currentYieldMethod"
                    style="width: 100%"
                    @update:model-value="setYieldMethodValue($event)"
                  >
                    <el-option
                      v-for="method in YIELD_METHOD_OPTIONS"
                      :key="method"
                      :label="method"
                      :value="method"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="showCurveFields" label="标准曲线斜率" class="settings-item">
                  <el-input v-model="gcMsYield.curve_slope" />
                </el-form-item>
                <el-form-item v-if="showCurveFields" label="标准曲线截距" class="settings-item">
                  <el-input v-model="gcMsYield.curve_intercept" />
                </el-form-item>
                <el-form-item v-if="showResponseFactorField" label="响应因子" class="settings-item">
                  <el-input v-model="gcMsYield.response_factor" />
                </el-form-item>
              </div>
              <div v-if="internalStandardSmilesError !== ''" class="yield-inline-error">
                {{ internalStandardSmilesError }}
              </div>
            </section>

            <section class="analysis-block">
              <div class="settings-section">目标产物表</div>
              <div class="button-row table-button-row">
                <el-button :icon="Plus" @click="addGcProductRow">新增行</el-button>
                <el-button :icon="Delete" @click="removeGcProductRow">删除行</el-button>
                <el-button :icon="Delete" @click="clearGcProductSelection">清除内容</el-button>
                <el-button :icon="DeleteFilled" @click="clearAllGcProductContent">清除所有内容</el-button>
                <el-button type="primary" :icon="DocumentChecked" @click="saveReactionTemplateOnly">
                  保存
                </el-button>
              </div>
              <div class="spreadsheet-wrap">
                <EditableSpreadsheet
                  :key="gcProductSpreadsheetKey"
                  ref="gcProductSpreadsheetRef"
                  :model-value="gcProductSpreadsheetRows"
                  :col-headers="GC_PRODUCT_HEADERS"
                  :columns="gcProductColumns"
                  :height="420"
                  :row-heights="88"
                  @update:model-value="updateGcProductRows"
                  @selected-row="selectedGcProductRow = $event"
                />
              </div>
            </section>
          </div>
        </el-tab-pane>

      </el-tabs>
    </section>

    <el-dialog
      v-model="historyDialogVisible"
      title="载入历史数据"
      width="720px"
      destroy-on-close
    >
      <div class="history-toolbar">
        <el-input
          v-model="historyQuery"
          clearable
          placeholder="搜索实验名称"
          @clear="searchHistoryList"
          @keyup.enter="searchHistoryList"
        />
        <el-button :icon="Search" @click="searchHistoryList">搜索</el-button>
      </div>

      <el-table
        v-loading="historyLoading"
        :data="historyItems"
        border
        empty-text="暂无可载入的历史数据"
      >
        <el-table-column prop="task_id" label="实验ID" width="120" />
        <el-table-column prop="task_name" label="实验名称" min-width="260" />
        <el-table-column prop="experiment_count" label="实验个数" width="120" />
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :loading="loadingHistoryTaskId === row.task_id"
              @click="loadHistoricalTemplate(row.task_id)"
            >
              载入
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="history-pagination">
        <el-pagination
          :current-page="historyPage"
          :page-size="HISTORY_PAGE_SIZE"
          :total="historyTotal"
          layout="total, prev, pager, next"
          @current-change="onHistoryPageChange"
        />
      </div>
    </el-dialog>

    <JobPanel :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.editor-panel {
  position: relative;
  z-index: 2;
  padding: 12px 14px;
}

.editor-panel :deep(.panel-title),
.editor-panel .panel-title {
  margin-bottom: 10px;
}

.editor-button-row {
  gap: 6px;
}

.history-load-button {
  color: #ffffff;
  background: #16b6c9;
  border-color: #16b6c9;
}

.history-load-button:hover,
.history-load-button:focus {
  color: #ffffff;
  background: #38c4d4;
  border-color: #38c4d4;
}

.history-load-button:active {
  color: #ffffff;
  background: #0fa2b7;
  border-color: #0fa2b7;
}

.editor-tabs {
  width: 100%;
}

.editor-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.editor-tabs :deep(.el-tabs__content) {
  min-width: 0;
  overflow: visible;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  align-items: start;
  margin-bottom: 14px;
}

.settings-column {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.settings-group,
.analysis-block {
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

.analysis-tab-body {
  display: grid;
  gap: 14px;
}

.yield-form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 12px;
  align-items: start;
  min-width: 0;
  padding-left: 10px;
}

.yield-inline-error {
  padding-left: 10px;
  color: #c45656;
  font-size: 12px;
  line-height: 18px;
}

.history-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.history-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
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
  .analysis-method-grid,
  .yield-form-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .settings-column-right .settings-group-fields,
  .analysis-method-grid,
  .yield-form-grid,
  .settings-group-fields {
    grid-template-columns: 1fr;
  }

  .history-toolbar {
    grid-template-columns: 1fr;
  }

  .analysis-method-row {
    grid-template-columns: minmax(150px, 1fr) 88px;
  }
}
</style>
