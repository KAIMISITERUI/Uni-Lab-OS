<script setup lang="ts">
import { computed, ref, watch, type CSSProperties } from 'vue'
import { ElMessage } from 'element-plus'
import { HotTable } from '@handsontable/vue3'
import { registerAllModules } from 'handsontable/registry'
import 'handsontable/styles/handsontable.min.css'
import 'handsontable/styles/ht-theme-main.min.css'

type SpreadsheetRow = Record<string, unknown> | unknown[]
type SpreadsheetColumn = Record<string, unknown>
type AutofillDirection = 'up' | 'down' | 'left' | 'right'
type FillMode = 'increment' | 'copy'
type CellCoordsLike = {
  row: number
  col: number
}
type CellRangeLike = {
  from?: CellCoordsLike
  to?: CellCoordsLike
  getTopLeftCorner?: () => CellCoordsLike
  getBottomRightCorner?: () => CellCoordsLike
  getHeight?: () => number
  getWidth?: () => number
}
type RangeBox = {
  top: number
  bottom: number
  left: number
  right: number
  height: number
  width: number
}
type SelectedRowRange = {
  start: number
  end: number
}
type HotCellChange = [number, number, unknown]
type HotInstanceLike = {
  destroyEditor: (revertOriginal?: boolean, prepareEditorIfNeeded?: boolean) => void
  getSourceData: () => SpreadsheetRow[]
  loadData: (data: SpreadsheetRow[], source?: string) => void
  getSelectedRangeLast: () => CellRangeLike | undefined
  getDataAtCell: (row: number, col: number) => unknown
  getCellMeta: (row: number, col: number) => { readOnly?: boolean }
  setDataAtCell: (changes: HotCellChange[], source?: string) => void
  countRows: () => number
  countCols: () => number
  render: () => void
}
type IncrementTarget =
  | { kind: 'number'; value: number }
  | {
      kind: 'text'
      value: number
      prefix: string
      suffix: string
      decimals: number
      width: number
    }
type IncrementSeed = {
  index: number
  target: IncrementTarget
}

const props = withDefaults(
  defineProps<{
    modelValue: SpreadsheetRow[]
    colHeaders: string[]
    columns: SpreadsheetColumn[]
    height?: string | number
    rowHeights?: number | number[]
    rowHeaders?: boolean
    stretchH?: 'all' | 'last' | 'none'
    mobileMinWidth?: number | 'auto'
  }>(),
  {
    height: 380,
    rowHeaders: true,
    stretchH: 'none',
    mobileMinWidth: 'auto',
  },
)

const emit = defineEmits<{
  'update:modelValue': [rows: SpreadsheetRow[]]
  'selected-row': [rowIndex: number | null]
}>()

registerAllModules()

const tableData = ref<SpreadsheetRow[]>(cloneRows(props.modelValue))
const hotTableRef = ref<
  (InstanceType<typeof HotTable> & {
    hotInstance?: HotInstanceLike
  }) | null
>(null)
const selectedRange = ref<RangeBox | null>(null)
let skipNextModelReload = false

const normalizedColumns = computed(() => {
  return props.columns.map((column) => {
    if (column.type === 'dropdown' || column.type === 'autocomplete') {
      return {
        ...column,
        trimDropdown: true,
      }
    }
    return column
  })
})

const mobileTableMinWidth = computed(() => {
  if (props.mobileMinWidth !== 'auto') {
    return Math.max(Number(props.mobileMinWidth), 320)
  }
  const rowHeaderWidth = props.rowHeaders === true ? 54 : 0
  const columnsWidth = props.columns.reduce((total, column) => total + resolveColumnWidth(column), 0)
  return Math.max(columnsWidth + rowHeaderWidth, 320)
})

const spreadsheetInnerStyle = computed<CSSProperties>(() => {
  return {
    '--editable-spreadsheet-mobile-min-width': `${mobileTableMinWidth.value}px`,
  } as CSSProperties
})

watch(
  () => props.modelValue,
  (rows) => {
    const nextRows = cloneRows(rows)
    tableData.value = nextRows
    if (skipNextModelReload === true) {
      skipNextModelReload = false
      return
    }
    const hotInstance = getHotInstance()
    if (hotInstance !== undefined) {
      hotInstance.loadData(cloneRows(nextRows), 'loadData')
      hotInstance.render()
    }
  },
  { deep: true },
)

const hotSettings = computed(() => {
  return {
    data: tableData.value,
    columns: normalizedColumns.value,
    colHeaders: props.colHeaders,
    rowHeaders: props.rowHeaders,
    height: props.height,
    rowHeights: props.rowHeights,
    width: '100%',
    stretchH: props.stretchH,
    licenseKey: 'non-commercial-and-evaluation',
    copyPaste: true,
    // 禁止拖拽填充时在表格底部自动插入新行, 避免固定实验数表格冒出第 13 行.
    fillHandle: {
      autoInsertRow: false,
    },
    manualColumnResize: true,
    manualRowResize: true,
    autoWrapRow: true,
    autoWrapCol: true,
    outsideClickDeselects: false,
    className: 'htCenter htMiddle editable-spreadsheet-cell',
    beforeAutofill: (
      selectionData: unknown[][],
      sourceRange: CellRangeLike,
      targetRange: CellRangeLike,
      direction: AutofillDirection,
    ) => {
      return buildIncrementalFillData(selectionData, sourceRange, targetRange, direction)
    },
    afterChange: (_changes: unknown, source: string) => {
      if (source === 'loadData') {
        return
      }
      syncSourceData(true)
    },
    afterSelectionEnd: (row: number, col: number, row2: number, col2: number) => {
      selectedRange.value = buildRangeBoxFromCoords(row, col, row2, col2)
      emit('selected-row', row2 >= 0 ? row2 : null)
    },
    afterDeselect: () => {
      selectedRange.value = null
      emit('selected-row', null)
    },
  }
})

function cloneRows(rows: SpreadsheetRow[]): SpreadsheetRow[] {
  return rows.map((row) => {
    if (Array.isArray(row) === true) {
      return [...row]
    }
    return { ...row }
  })
}

function resolveColumnWidth(column: SpreadsheetColumn): number {
  const rawWidth = column.width ?? column.minWidth
  if (typeof rawWidth === 'number' && Number.isFinite(rawWidth) === true) {
    return Math.max(rawWidth, 72)
  }
  if (typeof rawWidth === 'string') {
    const parsedWidth = Number.parseFloat(rawWidth)
    if (Number.isFinite(parsedWidth) === true) {
      return Math.max(parsedWidth, 72)
    }
  }
  return 120
}

function getHotInstance(): HotInstanceLike | undefined {
  return hotTableRef.value?.hotInstance
}

function syncSourceData(skipModelReload = false): SpreadsheetRow[] {
  const hotInstance = getHotInstance()
  if (hotInstance !== undefined) {
    hotInstance.destroyEditor(false, false)
    tableData.value = cloneRows(hotInstance.getSourceData())
  }
  const rows = cloneRows(tableData.value)
  if (skipModelReload === true) {
    skipNextModelReload = true
  }
  emit('update:modelValue', rows)
  return rows
}

function getSelectedRowRange(): SelectedRowRange | null {
  const hotInstance = getHotInstance()
  const rangeBox = hotInstance !== undefined ? getActiveRangeBox(hotInstance) : selectedRange.value
  if (rangeBox === null) {
    return null
  }
  return {
    start: rangeBox.top,
    end: rangeBox.bottom,
  }
}

function fillSelectedRange(mode: FillMode): boolean {
  const hotInstance = getHotInstance()
  if (hotInstance === undefined) {
    ElMessage.warning('表格尚未就绪')
    return false
  }
  hotInstance.destroyEditor(false, false)
  const rangeBox = getActiveRangeBox(hotInstance)
  if (rangeBox === null) {
    ElMessage.warning('请先选择要填充的单元格区域')
    return false
  }
  const changes = buildSelectedRangeFillChanges(hotInstance, rangeBox, mode)
  if (changes.length === 0) {
    if (mode === 'increment') {
      ElMessage.warning('选区内没有可递增填充的数据')
    } else {
      ElMessage.warning('选区内没有可复制填充的数据')
    }
    return false
  }
  hotInstance.setDataAtCell(changes, `button-${mode}-fill`)
  hotInstance.render()
  return true
}

function clearSelectedRange(): boolean {
  // 清空当前选区内所有可编辑单元格的内容, 不动行结构.
  const hotInstance = getHotInstance()
  if (hotInstance === undefined) {
    ElMessage.warning('表格尚未就绪')
    return false
  }
  hotInstance.destroyEditor(false, false)
  const rangeBox = getActiveRangeBox(hotInstance)
  if (rangeBox === null) {
    ElMessage.warning('请先选择要清除的单元格区域')
    return false
  }
  const changes: HotCellChange[] = []
  for (let row = rangeBox.top; row <= rangeBox.bottom; row += 1) {
    for (let col = rangeBox.left; col <= rangeBox.right; col += 1) {
      if (isEditableCell(hotInstance, row, col) === false) {
        continue
      }
      changes.push([row, col, null])
    }
  }
  if (changes.length === 0) {
    ElMessage.warning('选区内没有可清除的单元格')
    return false
  }
  hotInstance.setDataAtCell(changes, 'button-clear-range')
  hotInstance.render()
  return true
}

defineExpose({
  fillSelectedRange,
  clearSelectedRange,
  getSelectedRowRange,
  syncSourceData,
})

function buildIncrementalFillData(
  selectionData: unknown[][],
  sourceRange: CellRangeLike,
  targetRange: CellRangeLike,
  direction: AutofillDirection,
): unknown[][] {
  const sourceBox = getRangeBox(sourceRange, selectionData.length, selectionData[0]?.length || 1)
  const targetBox = getRangeBox(targetRange, sourceBox.height, sourceBox.width)
  const result: unknown[][] = []

  for (let row = targetBox.top; row <= targetBox.bottom; row += 1) {
    const resultRow: unknown[] = []
    for (let col = targetBox.left; col <= targetBox.right; col += 1) {
      resultRow.push(buildAutofillCellValue(selectionData, sourceBox, row, col, direction))
    }
    result.push(resultRow)
  }
  return result
}

function buildSelectedRangeFillChanges(
  hotInstance: HotInstanceLike,
  rangeBox: RangeBox,
  mode: FillMode,
): HotCellChange[] {
  const changes: HotCellChange[] = []
  for (let col = rangeBox.left; col <= rangeBox.right; col += 1) {
    const cells = collectEditableColumnCells(hotInstance, rangeBox, col)
    if (cells.length === 0) {
      continue
    }
    const values = mode === 'increment' ? buildIncrementColumnValues(cells) : buildCopyColumnValues(cells)
    if (values === null) {
      continue
    }
    for (let index = 0; index < cells.length; index += 1) {
      if (isSameCellValue(cells[index].value, values[index]) === true) {
        continue
      }
      changes.push([cells[index].row, cells[index].col, values[index]])
    }
  }
  return changes
}

function collectEditableColumnCells(hotInstance: HotInstanceLike, rangeBox: RangeBox, col: number) {
  const cells: Array<{ row: number; col: number; value: unknown }> = []
  for (let row = rangeBox.top; row <= rangeBox.bottom; row += 1) {
    if (isEditableCell(hotInstance, row, col) === false) {
      continue
    }
    cells.push({
      row,
      col,
      value: hotInstance.getDataAtCell(row, col),
    })
  }
  return cells
}

function buildCopyColumnValues(cells: Array<{ value: unknown }>): unknown[] | null {
  if (cells.length === 0) {
    return null
  }
  const sourceValue = cells[0].value
  return cells.map(() => sourceValue)
}

function buildIncrementColumnValues(cells: Array<{ value: unknown }>): unknown[] | null {
  const seeds = buildIncrementSeeds(cells.map((cell) => cell.value))
  if (seeds.length === 0) {
    return null
  }
  const formatTarget = mergeIncrementTargetFormat(seeds)
  if (formatTarget === null) {
    return null
  }
  const step = inferSeedStep(seeds)
  if (step === null) {
    return null
  }
  const firstSeed = seeds[0]
  return cells.map((_cell, index) => {
    const nextValue = firstSeed.target.value + step * (index - firstSeed.index)
    return formatIncrementValue(formatTarget, nextValue)
  })
}

function buildAutofillCellValue(
  selectionData: unknown[][],
  sourceBox: ReturnType<typeof getRangeBox>,
  row: number,
  col: number,
  direction: AutofillDirection,
): unknown {
  if (isInsideRange(sourceBox, row, col) === true) {
    return getSelectionValue(selectionData, row - sourceBox.top, col - sourceBox.left)
  }
  if (direction === 'down') {
    const sourceCol = normalizeSelectionIndex(col - sourceBox.left, sourceBox.width)
    const values = selectionData.map((sourceRow) => sourceRow[sourceCol])
    return incrementSeriesValue(values, row - sourceBox.bottom)
  }
  if (direction === 'up') {
    const sourceCol = normalizeSelectionIndex(col - sourceBox.left, sourceBox.width)
    const values = selectionData.map((sourceRow) => sourceRow[sourceCol])
    return incrementSeriesValue(values, row - sourceBox.top)
  }
  if (direction === 'right') {
    const sourceRow = normalizeSelectionIndex(row - sourceBox.top, sourceBox.height)
    const values = selectionData[sourceRow] || []
    return incrementSeriesValue(values, col - sourceBox.right)
  }
  const sourceRow = normalizeSelectionIndex(row - sourceBox.top, sourceBox.height)
  const values = selectionData[sourceRow] || []
  return incrementSeriesValue(values, col - sourceBox.left)
}

function getRangeBox(range: CellRangeLike, fallbackHeight: number, fallbackWidth: number): RangeBox {
  const topLeft = range.getTopLeftCorner?.() || range.from || { row: 0, col: 0 }
  const bottomRight =
    range.getBottomRightCorner?.() ||
    range.to || {
      row: topLeft.row + Math.max(fallbackHeight, 1) - 1,
      col: topLeft.col + Math.max(fallbackWidth, 1) - 1,
    }
  const top = Math.min(topLeft.row, bottomRight.row)
  const bottom = Math.max(topLeft.row, bottomRight.row)
  const left = Math.min(topLeft.col, bottomRight.col)
  const right = Math.max(topLeft.col, bottomRight.col)
  return {
    top,
    bottom,
    left,
    right,
    height: Math.max(range.getHeight?.() || bottom - top + 1, 1),
    width: Math.max(range.getWidth?.() || right - left + 1, 1),
  }
}

function buildRangeBoxFromCoords(row: number, col: number, row2: number, col2: number): RangeBox | null {
  const top = Math.max(Math.min(row, row2), 0)
  const bottom = Math.max(row, row2)
  const left = Math.max(Math.min(col, col2), 0)
  const right = Math.max(col, col2)
  if (bottom < 0 || right < 0) {
    return null
  }
  return {
    top,
    bottom,
    left,
    right,
    height: bottom - top + 1,
    width: right - left + 1,
  }
}

function getActiveRangeBox(hotInstance: HotInstanceLike): RangeBox | null {
  const range = hotInstance.getSelectedRangeLast()
  const rawRangeBox =
    range !== undefined ? getRangeBox(range, range.getHeight?.() || 1, range.getWidth?.() || 1) : selectedRange.value
  if (rawRangeBox === null) {
    return null
  }
  const top = Math.max(rawRangeBox.top, 0)
  const bottom = Math.min(rawRangeBox.bottom, hotInstance.countRows() - 1)
  const left = Math.max(rawRangeBox.left, 0)
  const right = Math.min(rawRangeBox.right, hotInstance.countCols() - 1)
  if (top > bottom || left > right) {
    return null
  }
  return {
    top,
    bottom,
    left,
    right,
    height: bottom - top + 1,
    width: right - left + 1,
  }
}

function isInsideRange(range: RangeBox, row: number, col: number): boolean {
  return row >= range.top && row <= range.bottom && col >= range.left && col <= range.right
}

function getSelectionValue(selectionData: unknown[][], row: number, col: number): unknown {
  return selectionData[row]?.[col] ?? ''
}

function normalizeSelectionIndex(index: number, size: number): number {
  const safeSize = Math.max(size, 1)
  return ((index % safeSize) + safeSize) % safeSize
}

function incrementSeriesValue(values: unknown[], offset: number): unknown {
  const compactValues = values.length > 0 ? values : ['']
  const anchorIndex = offset >= 0 ? compactValues.length - 1 : 0
  const anchorValue = compactValues[anchorIndex]
  const anchorTarget = extractIncrementTarget(anchorValue)
  if (anchorTarget === null) {
    return anchorValue
  }
  const seeds = buildIncrementSeeds(compactValues)
  const step = inferSeedStep(seeds)
  if (step === null) {
    return anchorValue
  }
  return formatIncrementValue(anchorTarget, anchorTarget.value + step * offset)
}

function formatIncrementValue(target: IncrementTarget, nextValue: number): unknown {
  if (target.kind === 'number') {
    return normalizeNumberPrecision(nextValue)
  }
  return `${target.prefix}${formatNumericText(nextValue, target.decimals, target.width)}${target.suffix}`
}

function extractIncrementTarget(value: unknown): IncrementTarget | null {
  if (typeof value === 'number') {
    if (Number.isFinite(value) === false) {
      return null
    }
    return { kind: 'number', value }
  }
  const text = String(value ?? '').trim()
  if (text === '') {
    return null
  }
  const matches = Array.from(text.matchAll(/[+-]?\d+(?:\.\d+)?/g))
  if (matches.length === 0) {
    return null
  }
  const match = matches[matches.length - 1]
  const normalizedMatch = normalizeNumericMatch(text, match)
  if (normalizedMatch === null) {
    return null
  }
  const decimalPart = normalizedMatch.numberText.split('.')[1] || ''
  const integerPart = normalizedMatch.numberText.split('.')[0].replace(/^[+-]/, '')
  return {
    kind: 'text',
    value: Number(normalizedMatch.numberText),
    prefix: text.slice(0, normalizedMatch.start),
    suffix: text.slice(normalizedMatch.start + normalizedMatch.numberText.length),
    decimals: decimalPart.length,
    width: integerPart.length,
  }
}

function normalizeNumericMatch(
  text: string,
  match: RegExpMatchArray,
): { start: number; numberText: string } | null {
  if (match.index === undefined) {
    return null
  }
  let start = match.index
  let numberText = match[0]
  if ((numberText.startsWith('-') === true || numberText.startsWith('+') === true) && start > 0) {
    const previousChar = text[start - 1]
    if (/[A-Za-z0-9_\])]$/.test(previousChar) === true) {
      start += 1
      numberText = numberText.slice(1)
    }
  }
  if (numberText === '' || numberText === '+' || numberText === '-') {
    return null
  }
  return {
    start,
    numberText,
  }
}

function buildIncrementSeeds(values: unknown[]): IncrementSeed[] {
  const seeds: IncrementSeed[] = []
  for (let index = 0; index < values.length; index += 1) {
    if (isEmptyCellValue(values[index]) === true) {
      continue
    }
    const target = extractIncrementTarget(values[index])
    if (target === null) {
      return []
    }
    seeds.push({
      index,
      target,
    })
  }
  return seeds
}

function inferSeedStep(seeds: IncrementSeed[]): number | null {
  if (seeds.length === 0) {
    return null
  }
  if (mergeIncrementTargetFormat(seeds) === null) {
    return null
  }
  if (seeds.length === 1) {
    return 1
  }
  const first = seeds[0]
  const last = seeds[seeds.length - 1]
  const distance = last.index - first.index
  if (distance === 0) {
    return 1
  }
  const step = (last.target.value - first.target.value) / distance
  if (Number.isFinite(step) === false) {
    return null
  }
  return step
}

function mergeIncrementTargetFormat(seeds: IncrementSeed[]): IncrementTarget | null {
  if (seeds.length === 0) {
    return null
  }
  const firstTarget = seeds[0].target
  if (firstTarget.kind === 'number') {
    if (seeds.every((seed) => seed.target.kind === 'number') === false) {
      return null
    }
    return firstTarget
  }
  let decimals = firstTarget.decimals
  let width = firstTarget.width
  for (const seed of seeds) {
    if (seed.target.kind !== 'text') {
      return null
    }
    if (seed.target.prefix !== firstTarget.prefix || seed.target.suffix !== firstTarget.suffix) {
      return null
    }
    decimals = Math.max(decimals, seed.target.decimals)
    width = Math.max(width, seed.target.width)
  }
  return {
    ...firstTarget,
    decimals,
    width,
  }
}

function isEditableCell(hotInstance: HotInstanceLike, row: number, col: number): boolean {
  return hotInstance.getCellMeta(row, col).readOnly === true ? false : true
}

function isEmptyCellValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return true
  }
  if (typeof value === 'string' && value.trim() === '') {
    return true
  }
  return false
}

function isSameCellValue(currentValue: unknown, nextValue: unknown): boolean {
  return Object.is(currentValue, nextValue)
}

function normalizeNumberPrecision(value: number): number {
  return Number(value.toFixed(12))
}

function formatNumericText(value: number, decimals: number, width: number): string {
  if (decimals <= 0) {
    return formatIntegerText(Math.trunc(value), width)
  }
  const sign = value < 0 ? '-' : ''
  const fixedText = Math.abs(value).toFixed(decimals)
  const [integerText, decimalText] = fixedText.split('.')
  return `${sign}${integerText.padStart(width, '0')}.${decimalText}`
}

function formatIntegerText(value: number, width: number): string {
  const sign = value < 0 ? '-' : ''
  const absText = String(Math.abs(value)).padStart(width, '0')
  return `${sign}${absText}`
}
</script>

<template>
  <div class="editable-spreadsheet">
    <div class="editable-spreadsheet-inner" :style="spreadsheetInnerStyle">
      <HotTable ref="hotTableRef" :settings="hotSettings" />
    </div>
  </div>
</template>

<style scoped>
.editable-spreadsheet {
  width: 100%;
  min-width: 0;
  overflow: auto hidden;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #ffffff;
  -webkit-overflow-scrolling: touch;
}

.editable-spreadsheet-inner {
  min-width: 100%;
}

.editable-spreadsheet :deep(.handsontable) {
  color: #172033;
  font-family:
    Inter, "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
  font-size: 13px;
}

.editable-spreadsheet :deep(.handsontable th) {
  color: #172033;
  font-weight: 700;
  text-align: center;
  vertical-align: middle;
  background: #eef4fb;
}

.editable-spreadsheet :deep(.handsontable tbody th) {
  padding: 0;
  vertical-align: middle;
}

.editable-spreadsheet :deep(.handsontable tbody th .relative) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 100%;
}

.editable-spreadsheet :deep(.handsontable tbody th .rowHeader) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  line-height: 1;
  text-align: center;
}

.editable-spreadsheet :deep(.handsontable td) {
  color: #24344d;
  text-align: center;
  vertical-align: middle;
}

.editable-spreadsheet :deep(.handsontable td.current),
.editable-spreadsheet :deep(.handsontable td.area) {
  background: #eaf3ff;
}

@media (max-width: 767.98px) {
  .editable-spreadsheet-inner {
    min-width: var(--editable-spreadsheet-mobile-min-width);
  }
}
</style>
