<template>
  <div :id="containerId" ref="containerRef" class="ntu-station-graph"></div>
</template>

<script setup lang="ts">
/**
 * 功能:
 *   在 Synthesis 页耗材卡和试剂表格之间, 嵌入 NTU 工作站等距 3D 视图.
 *   组件挂载时实例化 zrender + Station + 资源轮询, 卸载时清理.
 *   纯画布, 无标题栏, 撑满父容器.
 */
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { StationGraph } from '@/lib/dynamic-graph/runtime/useStationGraph'

const containerRef = ref<HTMLDivElement>()
const containerId = `ntu-graph-${Math.random().toString(36).slice(2, 9)}`
let graph: StationGraph | null = null

function handleResize (): void { graph?.onResize() }

onMounted(() => {
  graph = new StationGraph({ containerId })
  graph.mount()
  graph.startPolling(10_000)
  window.addEventListener('resize', handleResize)
})

onActivated(() => { graph?.startPolling(10_000) })
onDeactivated(() => { graph?.stopPolling() })

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  graph?.destroy()
  graph = null
})
</script>

<style scoped>
.ntu-station-graph {
  width: 100%;
  height: 720px;
  background: linear-gradient(180deg, #f6f9ff 0%, #eef3fb 100%);
  border-radius: 8px;
  box-sizing: border-box;
}
</style>
