<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { HotTable } from '@handsontable/vue3'
import { registerAllModules } from 'handsontable/registry'
import 'handsontable/styles/handsontable.min.css'
import 'handsontable/styles/ht-theme-main.min.css'

type SpreadsheetRow = Record<string, unknown> | unknown[]
type SpreadsheetColumn = Record<string, unknown>
type AutofillDirection = 'up' | 'down' | 'left' | 'right'
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

const props = withDefaults(
  defineProps<{
    modelValue: SpreadsheetRow[]
    colHeaders: string[]
    columns: SpreadsheetColumn[]
    height?: string | number
    rowHeaders?: boolean
    stretchH?: 'all' | 'last' | 'none'
  }>(),
  {
    height: 380,
    rowHeaders: true,
    stretchH: 'none',
  },
)

const emit = defineEmits<{
  'update:modelValue': [rows: SpreadsheetRow[]]
  'selected-row': [rowIndex: number | null]
}>()

registerAllModules()

const tableData = ref<SpreadsheetRow[]>(cloneRows(props.modelValue))

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

watch(
  () => props.modelValue,
  (rows) => {
    tableData.value = cloneRows(rows)
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
    width: '100%',
    stretchH: props.stretchH,
    licenseKey: 'non-commercial-and-evaluation',
    copyPaste: true,
    fillHandle: true,
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
      emit('update:modelValue', cloneRows(tableData.value))
    },
    afterSelectionEnd: (row: number) => {
      emit('selected-row', row >= 0 ? row : null)
    },
    afterDeselect: () => {
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

function getRangeBox(range: CellRangeLike, fallbackHeight: number, fallbackWidth: number) {
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

function isInsideRange(range: ReturnType<typeof getRangeBox>, row: number, col: number): boolean {
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
  const step = inferSeriesStep(compactValues)
  return incrementCellValue(anchorValue, step * offset)
}

function inferSeriesStep(values: unknown[]): number {
  if (values.length < 2) {
    return 1
  }
  const first = extractIncrementTarget(values[0])
  const last = extractIncrementTarget(values[values.length - 1])
  if (first === null || last === null) {
    return 1
  }
  const step = (last.value - first.value) / (values.length - 1)
  if (Number.isFinite(step) === false) {
    return 1
  }
  return step
}

function incrementCellValue(value: unknown, delta: number): unknown {
  const target = extractIncrementTarget(value)
  if (target === null) {
    return value
  }
  const nextValue = target.value + delta
  if (target.kind === 'number') {
    return nextValue
  }
  if (target.kind === 'numeric-text') {
    return formatNumericText(nextValue, target.decimals)
  }
  const nextInteger = Math.trunc(nextValue)
  return `${target.prefix}${formatIntegerText(nextInteger, target.width)}`
}

function extractIncrementTarget(value: unknown):
  | { kind: 'number'; value: number }
  | { kind: 'numeric-text'; value: number; decimals: number }
  | { kind: 'trailing-number'; value: number; prefix: string; width: number }
  | null {
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
  if (/^-?\d+(\.\d+)?$/.test(text) === true) {
    const decimalPart = text.split('.')[1] || ''
    return {
      kind: 'numeric-text',
      value: Number(text),
      decimals: decimalPart.length,
    }
  }
  const match = text.match(/^(.*?)(-?\d+)$/)
  if (match === null) {
    return null
  }
  return {
    kind: 'trailing-number',
    value: Number(match[2]),
    prefix: match[1],
    width: match[2].replace('-', '').length,
  }
}

function formatNumericText(value: number, decimals: number): string {
  if (decimals <= 0) {
    return String(Math.trunc(value))
  }
  return value.toFixed(decimals)
}

function formatIntegerText(value: number, width: number): string {
  const sign = value < 0 ? '-' : ''
  const absText = String(Math.abs(value)).padStart(width, '0')
  return `${sign}${absText}`
}
</script>

<template>
  <div class="editable-spreadsheet">
    <HotTable :settings="hotSettings" />
  </div>
</template>

<style scoped>
.editable-spreadsheet {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #ffffff;
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

.editable-spreadsheet :deep(.handsontable td) {
  color: #24344d;
  text-align: center;
  vertical-align: middle;
}

.editable-spreadsheet :deep(.handsontable td.current),
.editable-spreadsheet :deep(.handsontable td.area) {
  background: #eaf3ff;
}
</style>
