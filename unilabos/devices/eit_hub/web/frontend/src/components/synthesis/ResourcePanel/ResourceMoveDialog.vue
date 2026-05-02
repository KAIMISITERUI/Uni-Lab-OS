<template>
  <!--
    功能:
      移动资源对话框. 左侧选择源槽位, 右侧通过下拉菜单选择目标槽位.
      源槽位必须已有托盘且满足 moveOut, 目标槽位必须为空且满足 moveIn.
    事件:
      success: MoveTray 成功后通知父组件刷新主资源视图.
  -->
  <el-dialog
    :model-value="visible"
    width="92%"
    top="3vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="true"
    append-to-body
    :z-index="5000"
    destroy-on-close
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <template #header>
      <div class="dialog-title">移动资源</div>
    </template>
    <div class="dialog-body" v-loading="loading">
      <div class="two-col">
        <div class="col col-left">
          <div class="step-title"><span class="step-dot"></span>资源视图预览</div>
          <div class="col-inner preview-inner">
            <div class="position-input-bar">
              <el-input
                v-model="sourceInput"
                placeholder="源位置码 (回车加入)"
                clearable
                :prefix-icon="iconLocation"
                @change="onSourceInputCommit"
                @keyup.enter="onSourceInputCommit"
              />
            </div>
            <NTUStationGraph
              ref="graphRef"
              :margin="24"
              :auto-select-on-click="false"
              :on-click-tray="onClickTray"
            />
          </div>
        </div>
        <div class="col col-right">
          <div class="step-title"><span class="step-dot"></span>待移动资源</div>
          <div class="col-inner">
            <el-table
              :data="moveRows"
              :header-cell-style="{ background: '#EFF0F5', color: '#828AB0' }"
              empty-text=" "
              height="100%"
              style="width: 100%"
            >
              <el-table-column prop="source_layout_code" label="资源位置" width="76" header-align="center" />
              <el-table-column label="目标位置" min-width="108" header-align="center">
                <template #default="{ row }">
                  <el-select
                    v-model="row.destination_layout_code"
                    class="target-select"
                    filterable
                    clearable
                    placeholder="请选择目标位"
                    no-data-text="无可用目标位"
                    popper-class="resource-move-target-popper"
                    @change="(value) => onTargetSelect(row, value)"
                    @visible-change="(open) => onTargetSelectVisible(row, open)"
                  >
                    <el-option
                      v-for="code in getTargetOptions(row)"
                      :key="code"
                      :label="code"
                      :value="code"
                    />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="46" align="center" header-align="center">
                <template #default="{ row }">
                  <el-button
                    class="remove-icon-button"
                    link
                    :icon="iconRemove"
                    @click="removeRow(row.source_layout_code)"
                  />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onCancel">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onConfirm">确定</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Location, Remove } from '@element-plus/icons-vue'
import {
  getResourceInfo,
  moveTray,
  type MoveTrayItem,
} from '@/api/synthesis'
import { getModule } from '@/lib/dynamic-graph'
import { HIGHT_COLOR } from '@/lib/dynamic-graph/utils/consts'
import NTUStationGraph from '@/components/NTUStationGraph.vue'

type TrayOperate = 'moveIn' | 'moveOut'

interface ResourceRow {
  layout_code: string
  resource_type?: string
  tray_QR_code?: string
  [key: string]: unknown
}

interface MoveRow {
  source_layout_code: string
  destination_layout_code: string
  resource_type: string
  tray_QR_code?: string
}

interface Props {
  visible: boolean
  initialLayoutCode?: string
}
const props = withDefaults(defineProps<Props>(), { initialLayoutCode: '' })
const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'success'): void
}>()

const iconLocation = Location
const iconRemove = Remove
const TARGET_HIGHLIGHT_COLOR = '#f59e0b'

const loading = ref(false)
const submitting = ref(false)
const sourceInput = ref('')
const activeSourceCode = ref('')
const moveRows = ref<MoveRow[]>([])
const resourceMap = reactive<Record<string, ResourceRow>>({})
const graphRef = ref<InstanceType<typeof NTUStationGraph> | null>(null)
const highlightedCodes = new Set<string>()
let initialSourceTimer: number | undefined

watch(
  () => props.visible,
  (v) => {
    if (v === true) {
      resetState()
      void loadAndBuild()
    } else {
      resetState()
    }
  },
)

function resetState (): void {
  if (initialSourceTimer !== undefined) {
    window.clearTimeout(initialSourceTimer)
    initialSourceTimer = undefined
  }
  clearAllHighlights()
  sourceInput.value = ''
  activeSourceCode.value = ''
  moveRows.value = []
  Object.keys(resourceMap).forEach((key) => { delete resourceMap[key] })
}

async function loadAndBuild (): Promise<void> {
  loading.value = true
  try {
    await loadResources()
    const initial = normalizeLayoutCode(props.initialLayoutCode)
    if (initial !== '') {
      initialSourceTimer = window.setTimeout(() => {
        initialSourceTimer = undefined
        tryAddSource(initial)
      }, 300)
    }
  } finally {
    loading.value = false
  }
}

async function loadResources (): Promise<void> {
  try {
    const resp = await getResourceInfo({})
    const list = (resp?.resource_list as ResourceRow[] | undefined) || []
    list.forEach((item) => {
      const code = toTrimmedString(item.layout_code)
      if (code === '') {
        return
      }
      const topCode = toTopLayoutCode(code)
      const isTrayLevel = isTrayLevelLayoutCode(code)
      const resourceType = toOptionalString(item.resource_type)
      const trayQRCode = toOptionalString(item.tray_QR_code)
      const existing = resourceMap[topCode]
      if (existing === undefined) {
        resourceMap[topCode] = {
          layout_code: topCode,
          resource_type: isTrayLevel ? resourceType : undefined,
          tray_QR_code: isTrayLevel ? trayQRCode : undefined,
        }
        return
      }
      if (isTrayLevel === true) {
        if (existing.resource_type === undefined && resourceType !== undefined) {
          existing.resource_type = resourceType
        }
        if (existing.tray_QR_code === undefined && trayQRCode !== undefined) {
          existing.tray_QR_code = trayQRCode
        }
      }
    })
  } catch (err) {
    console.warn('[ResourceMoveDialog] getResourceInfo failed:', err)
    ElMessage.warning('加载资源失败, 请稍后重试')
  }
}

function toTopLayoutCode (layoutCode: string): string {
  const colonIdx = layoutCode.indexOf(':')
  if (colonIdx === -1) {
    return layoutCode
  }
  return layoutCode.slice(0, colonIdx)
}

function isTrayLevelLayoutCode (layoutCode: string): boolean {
  const colonIdx = layoutCode.indexOf(':')
  if (colonIdx === -1) {
    return true
  }
  return Number(layoutCode.slice(colonIdx + 1)) === -1
}

function normalizeLayoutCode (layoutCode: string | undefined): string {
  return toTrimmedString(layoutCode)
}

function toTrimmedString (value: unknown): string {
  if (value === undefined || value === null) {
    return ''
  }
  return String(value).trim()
}

function toOptionalString (value: unknown): string | undefined {
  const text = toTrimmedString(value)
  if (text === '') {
    return undefined
  }
  return text
}

function getStation (): any {
  return graphRef.value?.getStation?.() || null
}

function getSlot (layoutCode: string): any {
  return getStation()?.slots?.[layoutCode]
}

function hasTray (layoutCode: string): boolean {
  const slot = getSlot(layoutCode)
  return slot !== undefined && slot !== null && typeof slot.hasTray === 'function' && slot.hasTray() === true
}

function resolveTrayModel (layoutCode: string): string {
  const fromMap = toTrimmedString(resourceMap[layoutCode]?.resource_type)
  if (fromMap !== '') {
    return fromMap
  }
  const slot = getSlot(layoutCode)
  const fromTrayResource = toTrimmedString(slot?.tray?.resource?.resource_type)
  if (fromTrayResource !== '') {
    return fromTrayResource
  }
  return toTrimmedString(slot?.tray?.model)
}

function checkLayoutLimit (trayOp: TrayOperate, layoutCode: string, model: string): boolean {
  if (model === '') {
    return false
  }
  const limitList = getLayoutLimit(trayOp, layoutCode)
  return limitList.includes(model)
}

function getLayoutLimit (trayOp: TrayOperate, layoutCode: string): string[] {
  try {
    const module = getModule()
    const allModels = Object.keys(module.TrayMap || {})
    const container = module.container || 'NTU'
    const stationModel = getStation()?.stationModel
    const layoutConfigRoot = (module.ModelConfig?.layout_code as any)?.[container] || {}
    const layoutLimitMap = ((stationModel && layoutConfigRoot[stationModel]) || layoutConfigRoot)?.[trayOp] || {}

    const exactKey = Object.keys(layoutLimitMap).find((prefix: string) => layoutCode === prefix)
    const matchedKey = exactKey || Object.keys(layoutLimitMap).find((prefix: string) => {
      const prefixes = prefix.split(',')
      return prefixes.some((item: string) => layoutCode.startsWith(item))
    })
    if (matchedKey === undefined) {
      return allModels
    }

    const limitList = layoutLimitMap[matchedKey]
    if (Array.isArray(limitList) === false || limitList.includes('*')) {
      const excludeList = Array.isArray(limitList)
        ? limitList
          .filter((item: string) => item.startsWith('!'))
          .map((item: string) => item.slice(1))
        : []
      return allModels.filter((model) => excludeList.includes(model) === false)
    }
    return limitList
  } catch (err) {
    console.warn('[ResourceMoveDialog] getLayoutLimit failed:', err)
    return []
  }
}

function onClickTray (layoutCode: string): void {
  if (hasTray(layoutCode) === true) {
    toggleSourceByClick(layoutCode)
    return
  }
  ElMessage.info('请点击已有资源的源槽位, 目标槽位在右侧下拉选择')
}

function toggleSourceByClick (layoutCode: string): void {
  const existed = moveRows.value.find((row) => row.source_layout_code === layoutCode)
  if (existed !== undefined) {
    removeRow(layoutCode)
    return
  }
  tryAddSource(layoutCode)
}

function onSourceInputCommit (): void {
  const code = normalizeLayoutCode(sourceInput.value)
  if (code === '') {
    return
  }
  tryAddSource(code)
  sourceInput.value = ''
}

function tryAddSource (layoutCode: string): boolean {
  const slot = getSlot(layoutCode)
  if (slot === undefined || slot === null) {
    ElMessage.warning(`槽位 ${layoutCode} 不存在`)
    return false
  }
  if (hasTray(layoutCode) === false) {
    ElMessage.warning(`槽位 ${layoutCode} 无资源, 无法移动`)
    return false
  }
  const trayModel = resolveTrayModel(layoutCode)
  if (checkLayoutLimit('moveOut', layoutCode, trayModel) === false) {
    ElMessage.warning(`槽位 ${layoutCode} 的资源不允许移动`)
    return false
  }

  const existed = moveRows.value.find((row) => row.source_layout_code === layoutCode)
  if (existed !== undefined) {
    activateRow(layoutCode)
    return true
  }

  const row: MoveRow = {
    source_layout_code: layoutCode,
    destination_layout_code: '',
    resource_type: trayModel,
    tray_QR_code: resourceMap[layoutCode]?.tray_QR_code,
  }
  moveRows.value = [...moveRows.value, row]
  activeSourceCode.value = layoutCode
  refreshHighlights()
  return true
}

function isTargetUsed (layoutCode: string, sourceLayoutCode: string): boolean {
  return moveRows.value.some((row) => {
    return row.source_layout_code !== sourceLayoutCode && row.destination_layout_code === layoutCode
  })
}

function getTargetOptions (row: MoveRow): string[] {
  const station = getStation()
  const slots = station?.slots || {}
  const result = Object.keys(slots).filter((layoutCode) => {
    return isTargetSelectable(row, layoutCode, true)
  })
  return sortLayoutCodes(result)
}

function isTargetSelectable (row: MoveRow, layoutCode: string, allowCurrent: boolean): boolean {
  if (allowCurrent === true && layoutCode === row.destination_layout_code) {
    return true
  }
  const slot = getSlot(layoutCode)
  if (slot === undefined || slot === null || typeof slot.hasTray !== 'function') {
    return false
  }
  if (slot.hasTray() === true) {
    return false
  }
  if (layoutCode.startsWith('TB') === true) {
    return false
  }
  if (layoutCode === row.source_layout_code) {
    return false
  }
  if (isTargetUsed(layoutCode, row.source_layout_code) === true) {
    return false
  }
  return checkLayoutLimit('moveIn', layoutCode, row.resource_type) === true
}

function sortLayoutCodes (layoutCodes: string[]): string[] {
  return layoutCodes.slice().sort((a, b) => {
    const aParts = a.split(/[-:]/)
    const bParts = b.split(/[-:]/)
    const maxLen = Math.max(aParts.length, bParts.length)
    for (let index = 0; index < maxLen; index += 1) {
      const aPart = aParts[index] || ''
      const bPart = bParts[index] || ''
      const aNum = Number(aPart)
      const bNum = Number(bPart)
      if (Number.isFinite(aNum) === true && Number.isFinite(bNum) === true && aNum !== bNum) {
        return aNum - bNum
      }
      if (aPart !== bPart) {
        return aPart.localeCompare(bPart, 'zh-Hans-CN')
      }
    }
    return a.localeCompare(b, 'zh-Hans-CN')
  })
}

function normalizeSelectValue (value: unknown): string {
  return toTrimmedString(value)
}

function onTargetSelect (row: MoveRow, value: unknown): void {
  const targetCode = normalizeSelectValue(value)
  activeSourceCode.value = row.source_layout_code
  if (targetCode === '') {
    row.destination_layout_code = ''
    refreshHighlights()
    return
  }
  if (isTargetSelectable(row, targetCode, false) === false) {
    row.destination_layout_code = ''
    refreshHighlights()
    ElMessage.warning(`目标槽位 ${targetCode} 当前不可选`)
    return
  }
  row.destination_layout_code = targetCode
  refreshHighlights()
}

function onTargetSelectVisible (row: MoveRow, open: boolean): void {
  if (open === false) {
    return
  }
  activeSourceCode.value = row.source_layout_code
  if (getTargetOptions(row).length === 0) {
    ElMessage.warning(`源槽位 ${row.source_layout_code} 当前没有可用目标槽位`)
  }
}

function activateRow (sourceLayoutCode: string): void {
  if (moveRows.value.some((row) => row.source_layout_code === sourceLayoutCode) === false) {
    return
  }
  activeSourceCode.value = sourceLayoutCode
}

function removeRow (sourceLayoutCode: string): void {
  const row = moveRows.value.find((item) => item.source_layout_code === sourceLayoutCode)
  if (row === undefined) {
    return
  }
  moveRows.value = moveRows.value.filter((item) => item.source_layout_code !== sourceLayoutCode)
  if (activeSourceCode.value === sourceLayoutCode) {
    activeSourceCode.value = moveRows.value.find((item) => item.destination_layout_code === '')?.source_layout_code ||
      moveRows.value[0]?.source_layout_code ||
      ''
  }
  refreshHighlights()
}

function clearAllHighlights (): void {
  highlightedCodes.forEach((layoutCode) => {
    setSlotHighlight(layoutCode, false)
  })
  highlightedCodes.clear()
}

function refreshHighlights (): void {
  clearAllHighlights()
  moveRows.value.forEach((row) => {
    setSlotHighlight(row.source_layout_code, true, HIGHT_COLOR)
    highlightedCodes.add(row.source_layout_code)
    if (row.destination_layout_code !== '') {
      setSlotHighlight(row.destination_layout_code, true, TARGET_HIGHLIGHT_COLOR)
      highlightedCodes.add(row.destination_layout_code)
    }
  })
}

function setSlotHighlight (layoutCode: string, on: boolean, color?: string): void {
  const slot = getSlot(layoutCode)
  if (slot === undefined || slot === null || typeof slot.setHighlight !== 'function') {
    return
  }
  slot.setHighlight(on, on ? color : undefined)
}

async function onConfirm (): Promise<void> {
  if (moveRows.value.length === 0) {
    ElMessage.warning('请至少选择一个待移动资源')
    return
  }
  const missingTarget = moveRows.value.find((row) => row.destination_layout_code === '')
  if (missingTarget !== undefined) {
    activeSourceCode.value = missingTarget.source_layout_code
    ElMessage.warning(`请为源槽位 ${missingTarget.source_layout_code} 选择目标槽位`)
    return
  }
  for (const row of moveRows.value) {
    if (hasTray(row.source_layout_code) === false) {
      activeSourceCode.value = row.source_layout_code
      ElMessage.warning(`源槽位 ${row.source_layout_code} 已无资源, 请重新选择`)
      return
    }
    if (hasTray(row.destination_layout_code) === true) {
      activeSourceCode.value = row.source_layout_code
      ElMessage.warning(`目标槽位 ${row.destination_layout_code} 已有资源, 请重新选择`)
      return
    }
    if (row.destination_layout_code.startsWith('TB') === true) {
      activeSourceCode.value = row.source_layout_code
      ElMessage.warning('目标槽位不能选择 TB 交换仓, 请使用移出资源')
      return
    }
    if (isTargetUsed(row.destination_layout_code, row.source_layout_code) === true) {
      activeSourceCode.value = row.source_layout_code
      ElMessage.warning(`目标槽位 ${row.destination_layout_code} 已被其它移动项占用`)
      return
    }
    if (checkLayoutLimit('moveOut', row.source_layout_code, row.resource_type) === false ||
      checkLayoutLimit('moveIn', row.destination_layout_code, row.resource_type) === false) {
      activeSourceCode.value = row.source_layout_code
      ElMessage.warning(`移动项 ${row.source_layout_code} -> ${row.destination_layout_code} 不符合槽位规则`)
      return
    }
  }

  const layout_list: MoveTrayItem[] = moveRows.value.map((row) => ({
    source_layout_code: row.source_layout_code,
    destination_layout_code: row.destination_layout_code,
  }))

  submitting.value = true
  try {
    await moveTray({ layout_list })
    ElMessage.success('移动资源成功')
    emit('success')
    emit('update:visible', false)
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '移动资源失败'
    ElMessage.error(`移动资源失败: ${detail}`)
  } finally {
    submitting.value = false
  }
}

function onCancel (): void {
  emit('update:visible', false)
}
</script>

<style>
.resource-move-target-popper {
  z-index: 6000 !important;
}
</style>

<style scoped>
.dialog-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.dialog-body {
  height: 78vh;
  background: #fff;
  padding: 8px;
  border-radius: 6px;
  overflow: hidden;
}
.two-col {
  display: grid;
  grid-template-columns: minmax(420px, 1.45fr) minmax(230px, 0.36fr);
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.col {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  color: #303133;
  font-size: 14px;
  font-weight: 600;
  flex: 0 0 auto;
}
.step-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0dbf75;
  flex: 0 0 auto;
}
.col-inner {
  flex: 1 1 auto;
  min-height: 0;
  background: #fff;
  border-radius: 6px;
  padding: 10px;
  overflow: hidden;
}
.col-right .col-inner {
  padding: 0;
}
.preview-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px;
}
.preview-inner :deep(.ntu-station-graph) {
  flex: 1 1 auto;
  min-height: 0;
}
.position-input-bar {
  display: grid;
  grid-template-columns: minmax(180px, 240px);
  gap: 8px;
  flex: 0 0 auto;
}
.target-select {
  width: 100%;
}
.col-right :deep(.el-table th .cell),
.col-right :deep(.el-table td .cell) {
  white-space: nowrap;
}
.col-right :deep(.el-table .cell) {
  padding-left: 4px;
  padding-right: 4px;
}
.col-right :deep(.el-select__wrapper) {
  min-height: 30px;
  padding-left: 2px;
  padding-right: 0;
}
.col-right :deep(.el-select__placeholder) {
  font-size: 12px;
}
.col-right :deep(.el-select__suffix) {
  margin-left: 0;
}
.remove-icon-button {
  color: #111827;
  font-size: 18px;
}
.remove-icon-button:hover,
.remove-icon-button:focus {
  color: #f56c6c;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 767.98px) {
  .dialog-body {
    height: auto;
    min-height: 0;
    overflow: visible;
    padding: 0;
  }
  .two-col {
    grid-template-columns: 1fr;
    height: auto;
  }
  .col {
    height: auto;
    overflow: visible;
  }
  .preview-inner :deep(.ntu-station-graph) {
    max-height: 38vh;
  }
  .position-input-bar {
    grid-template-columns: 1fr;
  }
}
</style>
