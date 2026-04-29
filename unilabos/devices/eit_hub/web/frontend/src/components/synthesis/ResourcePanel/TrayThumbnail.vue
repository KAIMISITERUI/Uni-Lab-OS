<template>
  <!--
    功能:
      托盘 3D 缩略图. 在 160x160 容器内 init 一个独立 zrender 实例,
      调用 BaseTray.createAlone(tndir, zr) 渲染单托盘等距视图,
      并通过 trayIns.setResource({children}) 同步已选孔位高亮.
      参考 web_code TrayInfoV2.vue 的 initGraph + watchTrayChange 实现.
  -->
  <div :id="containerId" ref="containerRef" class="tray-thumbnail">
    <div ref="layerARef" :class="['thumbnail-layer', { 'is-active': activeLayer === 0 }]"></div>
    <div ref="layerBRef" :class="['thumbnail-layer', { 'is-active': activeLayer === 1 }]"></div>
    <span v-if="trayModel === ''" class="placeholder">请选择托盘型号</span>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { getModule } from '@/lib/dynamic-graph'
import {
  applyTrayVisualResource,
  buildTrayVisualResource,
  cancelTrayVisualRender,
  type TrayVisualResource,
  type TrayVisualWell,
} from '@/lib/dynamic-graph/utils/trayVisual'
import type { WellInfo } from './types'

interface Props {
  trayModel: string
  wells: WellInfo[]
  layoutCode: string
}
const props = defineProps<Props>()

const containerRef = ref<HTMLDivElement>()
const layerARef = ref<HTMLDivElement>()
const layerBRef = ref<HTMLDivElement>()
const containerId = `tray-thumb-${Math.random().toString(36).slice(2, 9)}`
const activeLayer = ref<0 | 1>(0)
const zrs: [any | null, any | null] = [null, null]
const trayInstances: [any | null, any | null] = [null, null]
let rebuildToken = 0

watch(
  () => props.trayModel,
  async (model) => {
    const token = ++rebuildToken
    if (model === '') {
      destroyAllLayers()
      return
    }
    await nextTick()
    await rebuild(model, token)
  },
  { immediate: true },
)

watch(
  () => props.wells.map((w) => `${w.state}:${w.with_cap}:${w.with_magneton}`).join('|'),
  () => {
    syncResourceToTray()
  },
)

function getLayerDom (layerIndex: 0 | 1): HTMLDivElement | undefined {
  return layerIndex === 0 ? layerARef.value : layerBRef.value
}

async function rebuild (model: string, token: number): Promise<void> {
  const targetLayer = activeLayer.value === 0 ? 1 : 0
  destroyLayer(targetLayer)
  const dom = getLayerDom(targetLayer)
  if (dom === undefined) { return }
  let nextZr: any = null
  let nextTray: any = null
  try {
    const module = getModule()
    // isBuild=true: fresh parse SVG, web_code TrayInfoV2.vue:286-294 同款
    nextTray = module.BaseTray.fromModel(model, true)
    if (nextTray === undefined || nextTray === null) { return }
    nextZr = module.Zrender.init(dom, { renderer: 'canvas' })
    zrs[targetLayer] = nextZr
    trayInstances[targetLayer] = nextTray
    const tndir: string = nextTray.config?.tray_tndir || 'tray_front'
    nextTray.createAlone(tndir, nextZr)
    setResourceToTray(nextTray)
    if (token !== rebuildToken) {
      if (zrs[targetLayer] === nextZr) {
        destroyLayer(targetLayer)
      }
      return
    }
    const oldLayer = activeLayer.value
    activeLayer.value = targetLayer
    await nextTick()
    if (oldLayer !== targetLayer) {
      destroyLayer(oldLayer)
    }
  } catch (err) {
    if (nextZr !== null && zrs[targetLayer] === nextZr) {
      destroyLayer(targetLayer)
    }
    console.error('[TrayThumbnail] rebuild failed:', err)
  }
}

function syncResourceToTray (): void {
  trayInstances.forEach((tray) => {
    setResourceToTray(tray)
  })
}

function setResourceToTray (tray: any): void {
  if (tray === undefined || tray === null || typeof tray.setResource !== 'function') { return }
  try {
    applyTrayVisualResource(tray, buildThumbnailResource(tray), 'thumbnail')
  } catch (err) {
    // 部分托盘 model 不支持完整 setResource, 容忍
    console.debug('[TrayThumbnail] setResource error:', err)
  }
}

function buildThumbnailResource (tray: any): TrayVisualResource {
  // 把已选孔位映射回 trayIns 内部 children, 字段对齐 web_code setResource 入参 (used + slot_index + resource_type + with_cap)
  // resource_type 必传, 否则 3D 不知道画哪个容器型号; 取自托盘 vessel_models[0] 默认
  const vesselType: string = tray?.config?.vessel_models?.[0] || ''
  const wells: TrayVisualWell[] = props.wells
    .filter((w) => w.state === 'filled')
    .map((w) => ({
      slotIndex: w.slotIndex,
      slotLabel: `${w.colLabel}${w.rowLabel}`,
      used: false,
      resourceType: vesselType,
      withCap: w.with_cap !== false,
      withMagneton: w.with_magneton === true,
    }))
  return buildTrayVisualResource({
    layoutCode: props.layoutCode,
    trayModel: props.trayModel,
    wells,
  })
}

function destroyLayer (layerIndex: 0 | 1): void {
  const tray = trayInstances[layerIndex]
  if (tray !== undefined && tray !== null) {
    cancelTrayVisualRender(tray)
    tray.zr = undefined
    tray.alone_group = undefined
  }
  try { zrs[layerIndex]?.dispose?.() } catch (_e) { /* noop */ }
  zrs[layerIndex] = null
  trayInstances[layerIndex] = null
  const dom = getLayerDom(layerIndex)
  if (dom !== undefined) {
    dom.replaceChildren()
  }
}

function destroyAllLayers (): void {
  destroyLayer(0)
  destroyLayer(1)
}

onBeforeUnmount(() => {
  rebuildToken++
  destroyAllLayers()
})
</script>

<style scoped>
.tray-thumbnail {
  /* 与下方下拉框/输入框对齐 (撑满 SlotConfigCard 左列宽度), 高度保持视觉占位 */
  width: 100%;
  height: 160px;
  background: #fff;
  border-radius: 6px;
  position: relative;
  overflow: hidden;
}
.thumbnail-layer {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
}
.thumbnail-layer.is-active {
  opacity: 1;
}
.placeholder {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #909399;
}
</style>
