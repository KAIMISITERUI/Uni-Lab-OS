<template>
  <div
    :id="containerId"
    ref="containerRef"
    :class="['ntu-station-graph', { 'is-ready': graphReady }]"
    :style="{ height: graphHeight }"
  ></div>
</template>

<script setup lang="ts">
/**
 * 功能:
 *   在 Synthesis 页耗材卡和试剂表格之间, 嵌入 NTU 工作站等距 3D 视图.
 *   组件挂载时实例化 zrender + Station + 资源轮询, 卸载时清理.
 *   纯画布, 无标题栏, 撑满父容器.
 */
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { StationGraph } from '@/lib/dynamic-graph/runtime/useStationGraph'

interface Props {
  margin?: number
  onClickTray?: (layout_code: string, x: number, y: number) => void
  onContextMenuTray?: (layout_code: string, x: number, y: number) => void
}

const props = withDefaults(defineProps<Props>(), {
  margin: 24,
})
const containerRef = ref<HTMLDivElement>()
const containerId = `ntu-graph-${Math.random().toString(36).slice(2, 9)}`
const graphHeight = ref('720px')
const graphReady = ref(false)
let graphContentRatio = 2.08
let graph: StationGraph | null = null
let resizeObserver: ResizeObserver | null = null
let resizeFrame: number | null = null
let layoutTaskId = 0

// 暴露刷新方法供父组件在录入资源后强制同步主 3D 视图
defineExpose({
  refresh: async (): Promise<void> => {
    await refreshAndSyncLayout(true)
  },
})

function handleResize (): void {
  scheduleResizeSync()
}

function updateGraphHeight (): boolean {
  const container = containerRef.value
  if (container === undefined) {
    return false
  }
  if (container.clientWidth <= 0) {
    return false
  }
  const graphMargin = normalizeGraphMargin()
  const availableWidth = Math.max(container.clientWidth - graphMargin * 2, 1)
  const height = availableWidth / graphContentRatio + graphMargin * 2
  graphHeight.value = `${height}px`
  return true
}

function normalizeGraphMargin (): number {
  const margin = Number(props.margin)
  if (Number.isFinite(margin) === false || margin < 0) {
    return 0
  }
  return margin
}

function waitForGraphPaint (): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve())
    })
  })
}

async function syncGraphLayout (): Promise<void> {
  const stationGraph = graph
  if (stationGraph === null) {
    return
  }
  const taskId = ++layoutTaskId
  await waitForGraphPaint()
  if (graph === stationGraph && taskId === layoutTaskId) {
    graphContentRatio = stationGraph.calibrateContentBounds()
    updateGraphHeight()
  }
  await nextTick()
  if (graph === stationGraph && taskId === layoutTaskId) {
    stationGraph.onResize()
  }
}

async function refreshAndSyncLayout (hideUntilSynced = false): Promise<void> {
  const stationGraph = graph
  if (stationGraph === null) {
    return
  }
  const shouldReveal = hideUntilSynced === true || graphReady.value === false
  if (shouldReveal === true) {
    graphReady.value = false
  }

  let refreshError: unknown = null
  try {
    await stationGraph.refresh()
  } catch (error) {
    refreshError = error
  }

  try {
    await syncGraphLayout()
  } finally {
    if (shouldReveal === true && graph === stationGraph) {
      graphReady.value = true
    }
  }

  if (refreshError !== null) {
    throw refreshError
  }
}

onMounted(async () => {
  await nextTick()
  updateGraphHeight()
  const stationGraph = new StationGraph({
    containerId,
    viewportPadding: normalizeGraphMargin(),
    onClickTray: (layout_code, x, y) => {
      if (typeof props.onClickTray === 'function') {
        props.onClickTray(layout_code, x, y)
      }
    },
    onContextMenuTray: (layout_code, x, y) => {
      if (typeof props.onContextMenuTray === 'function') {
        props.onContextMenuTray(layout_code, x, y)
      }
    },
    onAfterRefresh: () => {
      void syncGraphLayout()
    },
  })
  graph = stationGraph
  stationGraph.mount()
  window.addEventListener('resize', handleResize)
  setupResizeObserver()
  try {
    await refreshAndSyncLayout(true)
  } catch (error) {
    console.error('[StationGraph] refresh error:', error)
  }
  if (graph === stationGraph) {
    stationGraph.startPolling(10_000)
  }
})

watch(
  () => props.margin,
  () => {
    const graphMargin = normalizeGraphMargin()
    if (graph !== null) {
      graph.setViewportPadding(graphMargin)
    }
    scheduleResizeSync()
  },
)

onActivated(() => { graph?.startPolling(10_000) })
onDeactivated(() => { graph?.stopPolling() })

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFrame !== null) {
    window.cancelAnimationFrame(resizeFrame)
    resizeFrame = null
  }
  graph?.destroy()
  graph = null
})

function setupResizeObserver (): void {
  const container = containerRef.value
  if (container === undefined || typeof ResizeObserver === 'undefined') {
    return
  }
  resizeObserver = new ResizeObserver(() => {
    scheduleResizeSync()
  })
  resizeObserver.observe(container)
}

function scheduleResizeSync (): void {
  if (resizeFrame !== null) {
    window.cancelAnimationFrame(resizeFrame)
  }
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = null
    updateGraphHeight()
    void nextTick(() => {
      if (graph !== null) {
        graph.onResize()
      }
    })
  })
}
</script>

<style scoped>
.ntu-station-graph {
  width: 100%;
  height: 720px;
  background: #fff;
  border-radius: 8px;
  box-sizing: border-box;
  overflow: hidden;
}

.ntu-station-graph :deep(canvas) {
  opacity: 0;
  visibility: hidden;
}

.ntu-station-graph.is-ready :deep(canvas) {
  opacity: 1;
  visibility: visible;
}
</style>
