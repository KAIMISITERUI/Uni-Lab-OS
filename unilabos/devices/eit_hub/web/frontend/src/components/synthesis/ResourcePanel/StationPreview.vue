<template>
  <!--
    功能:
      录入资源对话框左栏 资源视图预览. 顶部 位置码 标签栏显示已选 layout_code (可移除),
      下方挂载完整 NTU 工站 3D 等距视图 (独立 StationGraph 实例), 点击槽位切换选中状态.
  -->
  <div class="station-preview">
    <div v-if="!hidePositionBar" class="position-bar">
      <el-input :model-value="positionLabel" placeholder="位置码" readonly :prefix-icon="iconLocation" />
      <div class="tag-list">
        <el-tag
          v-for="code in selectedCodes"
          :key="code"
          closable
          type="success"
          @close="emit('remove-slot', code)"
        >
          {{ code }}
        </el-tag>
      </div>
    </div>
    <div class="graph-wrap" ref="wrapRef">
      <div
        :id="containerId"
        ref="containerRef"
        :class="['dialog-station-graph', { 'tb-station-graph': isTbVisible }]"
      ></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch, nextTick, computed } from 'vue'
import { Location } from '@element-plus/icons-vue'
import { StationGraph } from '@/lib/dynamic-graph/runtime/useStationGraph'
import { getModule } from '@/lib/dynamic-graph'
import {
  applyTrayVisualResource,
  buildTrayVisualResource,
  type TrayVisualResource,
  type TrayVisualWell,
} from '@/lib/dynamic-graph/utils/trayVisual'
import type { TraySlot } from '@/lib/dynamic-graph/station/slot'

// 单个槽位的预览配置, 父组件汇总后传入
export interface SlotResourcePreview {
  layoutCode: string
  trayModel: string
  vesselType: string
  // 已选孔位列表, 元素含 slotIndex / with_cap
  filledWells: Array<{ slotIndex: number; with_cap: boolean; with_magneton: boolean }>
}

interface Props {
  selectedCodes: string[]
  slotResources?: SlotResourcePreview[]
  visiblePrefixes?: string[]
  disabledCodes?: string[]
  // 编辑场景由父组件接管位置码栏 (可编辑+扫码), 此处隐藏内置只读栏
  hidePositionBar?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  slotResources: () => [],
  visiblePrefixes: () => [],
  disabledCodes: () => [],
  hidePositionBar: false,
})
const emit = defineEmits<{
  (e: 'slot-click', layoutCode: string): void
  (e: 'disabled-slot-click', layoutCode: string): void
  (e: 'remove-slot', layoutCode: string): void
  (e: 'station-ready', station: any): void
}>()

const iconLocation = Location
const containerRef = ref<HTMLDivElement>()
const wrapRef = ref<HTMLDivElement>()
const containerId = `dialog-ntu-graph-${Math.random().toString(36).slice(2, 9)}`
let graph: StationGraph | null = null
let resizeObserver: ResizeObserver | null = null
let layoutTaskId = 0
let layoutTimer: ReturnType<typeof setTimeout> | null = null
const TB_ACCESSORY_NAMES = new Set(['tb-tray-link', 'tb-link-back', 'tb-link-left', 'tb-link-left-front'])

const positionLabel = computed(() => {
  if (props.selectedCodes.length === 0) { return '' }
  return `已选 ${props.selectedCodes.length} 个位置`
})
const isTbVisible = computed(() => props.visiblePrefixes.some((prefix) => prefix === 'TB-' || prefix === 'TB'))

function waitForGraphPaint (): Promise<void> {
  // 双 RAF 等待浏览器布局完成, 复用 NTUStationGraph 同款 hack
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve())
    })
  })
}

function scheduleGraphLayout (delay = 80): void {
  const taskId = ++layoutTaskId
  if (layoutTimer !== null) {
    clearTimeout(layoutTimer)
  }
  layoutTimer = setTimeout(() => {
    layoutTimer = null
    void syncGraphLayout(taskId)
  }, delay)
}

async function syncGraphLayout (taskId = ++layoutTaskId): Promise<void> {
  await nextTick()
  if (taskId !== layoutTaskId) { return }
  if (graph !== null) {
    applyVisiblePrefixes()
    graph.fitVisibleScene(resolveSceneBoundsPadding())
    graph.onResize()
    applyVisiblePrefixes()
  }
}

async function refreshVisibleResources (): Promise<void> {
  if (graph === null) { return }
  try {
    await graph.refresh()
  } catch (err) {
    console.error('[StationPreview] refresh visible resources error:', err)
  }
  syncSelectionToGraph()
  syncSlotResourcesToGraph()
  await syncGraphLayout()
}

function isLayoutCodeVisible (layoutCode: string): boolean {
  if (props.visiblePrefixes.length === 0) {
    return true
  }
  return props.visiblePrefixes.some((prefix) => layoutCode.startsWith(prefix))
}

function isLayoutCodeDisabled (layoutCode: string): boolean {
  return props.disabledCodes.some((code) => code === layoutCode)
}

onMounted(async () => {
  const stationGraph = new StationGraph({
    containerId,
    viewportPadding: 24,
    autoSelectOnClick: false,
    preserveFilteredOutResources: true,
    onClickTray: (layout_code) => {
      if (isLayoutCodeVisible(layout_code) === true) {
        if (isLayoutCodeDisabled(layout_code) === true) {
          emit('disabled-slot-click', layout_code)
          return
        }
        emit('slot-click', layout_code)
      }
    },
    onAfterRefresh: () => {
      scheduleGraphLayout()
    },
    resourceLayoutFilter: (layoutCode) => isLayoutCodeVisible(layoutCode),
  })
  graph = stationGraph
  stationGraph.mount()
  applyVisiblePrefixes()
  try {
    await stationGraph.refresh()
  } catch (err) {
    console.error('[StationPreview] refresh error:', err)
  }
  emit('station-ready', stationGraph.station)
  // 关键: el-dialog 打开过程中容器宽高有过渡, 必须显式触发 syncGraphLayout
  await syncGraphLayout()
  syncSelectionToGraph()
  // ResizeObserver 兜底: 任何尺寸变化都触发一次 graph 重排, 避免折叠/动画后看不见
  if (wrapRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      scheduleGraphLayout()
    })
    resizeObserver.observe(wrapRef.value)
  }
  window.addEventListener('resize', onResize)
})

watch(() => props.selectedCodes.join(','), () => { syncSelectionToGraph() })

watch(
  () => props.visiblePrefixes.join(','),
  () => {
    void syncGraphLayout()
    void refreshVisibleResources()
  },
)

// slotResources 变化时同步预览到对应槽位的 tray, 让左侧大 3D 视图实时反映右侧选择
watch(
  () => JSON.stringify(props.slotResources),
  () => {
    syncSlotResourcesToGraph()
  },
  { immediate: false },
)

function syncSelectionToGraph (): void {
  if (graph === null) { return }
  const station: any = graph.station
  if (!station) { return }
  const slotMap: Record<string, TraySlot> = station.slots
  const nextSelectedCodes = new Set(
    props.selectedCodes.filter((code) => isLayoutCodeVisible(code) === true),
  )
  Object.values(slotMap).forEach((slot: TraySlot) => {
    const shouldSelect = nextSelectedCodes.has(slot.layout_code)
    if (slot.selected !== shouldSelect) {
      slot.setSelected(shouldSelect, '#0dbf75')
    }
  })
  applyVisiblePrefixes()
}

// 已对当前会话挂上预览 tray 的槽位集合, 关闭对话框时父组件 destroy-on-close 会重建整个组件, 不需手动清理
const previewedSlots = new Set<string>()

function syncSlotResourcesToGraph (): void {
  if (graph === null) { return }
  const station: any = graph.station
  if (!station) { return }
  const slotMap: Record<string, TraySlot> = station.slots
  const BaseTray = getModule().BaseTray
  // 当前预览中的槽位
  const currentCodes = new Set<string>()
  props.slotResources.forEach((sr) => {
    if (sr.trayModel) { currentCodes.add(sr.layoutCode) }
  })
  // 移除上一次预览但本次没有的槽位
  Array.from(previewedSlots).forEach((code) => {
    if (!currentCodes.has(code)) {
      const slot: any = slotMap[code]
      if (slot && typeof slot.removeTray === 'function' && slot.hasTray?.()) {
        slot.removeTray()
      }
      previewedSlots.delete(code)
    }
  })
  // 写入/更新本次预览
  props.slotResources.forEach((sr) => {
    if (!sr.trayModel) { return }
    const slot: any = slotMap[sr.layoutCode]
    if (!slot) { return }
    const resource = buildPreviewResource(sr)
    let trayInstance: any = slot.tray
    const needNewTray = !trayInstance || trayInstance.model !== sr.trayModel
    if (needNewTray) {
      try {
        if (BaseTray) {
          const oldTray = slot.tray
          trayInstance = BaseTray.fromModel(sr.trayModel)
          slot.setTray(trayInstance)
          if (oldTray && oldTray !== trayInstance) {
            oldTray.remove?.(station.trays_group)
          }
        }
      } catch (err) {
        console.warn('[StationPreview] preview setTray failed:', err)
        return
      }
    }
    if (!trayInstance) { return }
    try {
      applyTrayVisualResource(trayInstance, resource, 'station')
    } catch (err) {
      console.debug('[StationPreview] tray.setResource error:', err)
    }
    previewedSlots.add(sr.layoutCode)
  })
  applyVisiblePrefixes()
}

function buildPreviewResource (sr: SlotResourcePreview): TrayVisualResource {
  const wells: TrayVisualWell[] = sr.filledWells.map((w) => ({
    slotIndex: w.slotIndex,
    resourceType: sr.vesselType,
    used: false,
    withCap: w.with_cap !== false,
    withMagneton: w.with_magneton === true,
  }))

  return buildTrayVisualResource({
    layoutCode: sr.layoutCode,
    trayModel: sr.trayModel,
    wells,
  })
}

function applyVisiblePrefixes (): void {
  if (graph === null) { return }
  const station: any = graph.station
  if (station === undefined || station === null) { return }
  applyStationBaseVisibility(station)
  applyTrayVisibility(station)
  station.zr?.flush?.()
}

function applyStationBaseVisibility (station: any): void {
  const root = station.res?.root
  if (root === undefined || root === null) { return }
  if (props.visiblePrefixes.length === 0) {
    setSubtreeVisibility(root, true)
    return
  }

  const keepNodes = new Set<any>()
  keepNodes.add(root)
  Object.values(station.slots || {}).forEach((slot: any) => {
    if (isLayoutCodeVisible(slot.layout_code) === false) { return }
    const slotNode = findLayoutNode(slot.zr_floor, slot.layout_code)
    const nodes = [slotNode, slot.zr_floor, slot.zr_label, slot.zr_text, slot.zr_part]
    nodes.forEach((node) => {
      if (node === undefined || node === null) { return }
      markAncestors(node, keepNodes)
      markSubtree(node, keepNodes)
    })
  })
  markSideAccessoryNodes(station, keepNodes)

  walkDisplayTree(root, (node) => {
    setDisplayableVisible(node, keepNodes.has(node))
  })
  root.show?.()
}

function applyTrayVisibility (station: any): void {
  const slots = Object.values(station.slots || {}) as any[]
  slots.forEach((slot) => {
    const visible = isLayoutCodeVisible(slot.layout_code)
    setDisplayableVisible(slot.tray?.res?.root, visible)
    setDisplayableVisible(slot.tray_select_z0_res?.root, visible && slot.selected === true)
    setDisplayableVisible(slot.tray_select_z1_res?.root, visible && slot.selected === true)
  })

  const trayChildren = station.trays_group?.children?.() || []
  trayChildren.forEach((child: any) => {
    const layoutCode = getLayoutCodeFromNode(child)
    if (layoutCode !== '' && isLayoutCodeVisible(layoutCode) === false) {
      setDisplayableVisible(child, false)
    }
  })
}

function findLayoutNode (startNode: any, layoutCode: string): any {
  let node = startNode?.parent || startNode
  while (node !== undefined && node !== null) {
    if (node._layout_code === layoutCode || node.item_name === `item_${layoutCode}` || node.name === `item_${layoutCode}`) {
      return node
    }
    node = node.parent
  }
  return startNode
}

function markSideAccessoryNodes (station: any, keepNodes: Set<any>): void {
  const namedItems = station.res?.named || []
  namedItems.forEach((item: any) => {
    const itemName = typeof item?.name === 'string' ? item.name : ''
    if (isVisibleSideAccessory(itemName) === false) { return }
    const node = item?.el
    if (node === undefined || node === null) { return }
    markAncestors(node, keepNodes)
    markSubtree(node, keepNodes)
  })
}

function isVisibleSideAccessory (name: string): boolean {
  if (TB_ACCESSORY_NAMES.has(name) === true) {
    return props.visiblePrefixes.some((prefix) => prefix === 'TB-' || prefix === 'TB')
  }
  return false
}

function resolveSceneBoundsPadding (): { topRatio: number; rightRatio: number; bottomRatio: number; leftRatio: number } {
  if (isTbVisible.value === false) {
    return { topRatio: 0, rightRatio: 0, bottomRatio: 0, leftRatio: 0 }
  }
  return {
    topRatio: 0.18,
    rightRatio: 0.02,
    bottomRatio: 0.18,
    leftRatio: 0.02,
  }
}

function getLayoutCodeFromNode (node: any): string {
  let current = node
  while (current !== undefined && current !== null) {
    if (typeof current._layout_code === 'string') {
      return current._layout_code
    }
    current = current.parent
  }
  return ''
}

function markAncestors (node: any, keepNodes: Set<any>): void {
  let current = node
  while (current !== undefined && current !== null) {
    keepNodes.add(current)
    current = current.parent
  }
}

function markSubtree (node: any, keepNodes: Set<any>): void {
  keepNodes.add(node)
  const children = node?.children?.() || []
  children.forEach((child: any) => markSubtree(child, keepNodes))
}

function walkDisplayTree (node: any, callback: (node: any) => void): void {
  callback(node)
  const children = node?.children?.() || []
  children.forEach((child: any) => walkDisplayTree(child, callback))
}

function setSubtreeVisibility (node: any, visible: boolean): void {
  walkDisplayTree(node, (item) => {
    setDisplayableVisible(item, visible)
  })
}

function setDisplayableVisible (node: any, visible: boolean): void {
  if (node === undefined || node === null) { return }
  if (visible === true) {
    node.show?.()
  } else {
    node.hide?.()
  }
  node.dirty?.()
}

function onResize (): void {
  scheduleGraphLayout(30)
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (layoutTimer !== null) {
    clearTimeout(layoutTimer)
    layoutTimer = null
  }
  resizeObserver?.disconnect()
  resizeObserver = null
  graph?.destroy()
  graph = null
})
</script>

<style scoped>
.station-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
}
.position-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px 10px;
}
.position-bar :deep(.el-input) {
  width: 200px;
  flex: 0 0 auto;
}
.tag-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1 1 auto;
  min-width: 0;
}
.graph-wrap {
  flex: 1 1 auto;
  min-height: 0;
  background: #fff;
  border: 1px solid #dce5f0;
  border-radius: 6px;
  box-sizing: border-box;
  overflow: hidden;
  position: relative;
}
.dialog-station-graph {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

@media (max-width: 767.98px) {
  .station-preview {
    min-height: 200px;
    max-height: 38vh;
  }

  .position-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .position-bar :deep(.el-input) {
    width: 100%;
  }

  .tag-list :deep(.el-tag) {
    min-height: 28px;
    border-color: #0dbf75;
    background: #e8fff5;
    color: #087d52;
  }
}
</style>
