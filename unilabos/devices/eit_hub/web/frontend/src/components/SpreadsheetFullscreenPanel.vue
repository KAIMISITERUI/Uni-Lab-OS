<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'
import { Close, FullScreen } from '@element-plus/icons-vue'
import { useViewportMode } from '../composables/useViewportMode'

type TableHeight = string | number

const props = withDefaults(
  defineProps<{
    title: string
    normalHeight?: TableHeight
    fullscreenTableOffset?: number
    mobileFullscreenTableOffset?: number
    mobileLandscape?: boolean
  }>(),
  {
    normalHeight: 500,
    fullscreenTableOffset: 0,
    mobileLandscape: true,
  },
)

const emit = defineEmits<{
  (e: 'fullscreen-change', value: boolean): void
  (e: 'layout-change'): void
}>()

const slots = useSlots()
const { isMobile } = useViewportMode()
const rootRef = ref<HTMLDivElement | null>(null)
const bodyRef = ref<HTMLDivElement | null>(null)
const fullscreenActive = ref(false)
const measuredBodyHeight = ref(0)
let resizeObserver: ResizeObserver | null = null
let measureFrame: number | null = null

const hasActions = computed(() => slots.actions !== undefined)

const currentTableHeight = computed<TableHeight>(() => {
  if (fullscreenActive.value === false) {
    return props.normalHeight
  }
  const fallbackHeight = Math.max(Math.floor((window.visualViewport?.height ?? window.innerHeight) - 150), 260)
  const bodyHeight = measuredBodyHeight.value > 0 ? measuredBodyHeight.value : fallbackHeight
  const offset = isMobile.value === true && props.mobileFullscreenTableOffset !== undefined
    ? props.mobileFullscreenTableOffset
    : props.fullscreenTableOffset
  return Math.max(Math.floor(bodyHeight - offset), 260)
})

function scheduleMeasure(): void {
  if (measureFrame !== null) {
    window.cancelAnimationFrame(measureFrame)
  }
  measureFrame = window.requestAnimationFrame(() => {
    measureFrame = null
    measureBody()
  })
}

function measureBody(): void {
  const body = bodyRef.value
  if (body === null) {
    measuredBodyHeight.value = 0
    return
  }
  measuredBodyHeight.value = body.clientHeight
}

function setupResizeObserver(): void {
  cleanupResizeObserver()
  const body = bodyRef.value
  if (body === null || typeof ResizeObserver === 'undefined') {
    return
  }
  resizeObserver = new ResizeObserver(() => {
    scheduleMeasure()
  })
  resizeObserver.observe(body)
}

function cleanupResizeObserver(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
}

function setBodyFullscreenClass(active: boolean): void {
  document.body.classList.toggle('spreadsheet-fullscreen-active', active)
}

async function requestBrowserFullscreen(): Promise<void> {
  const root = rootRef.value
  if (root === null || document.fullscreenElement !== null) {
    return
  }
  try {
    await root.requestFullscreen()
  } catch {
    // 浏览器拒绝全屏时, 仍使用固定定位铺满视口.
  }
}

function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve())
    })
  })
}

async function exitBrowserFullscreen(): Promise<void> {
  if (document.fullscreenElement !== rootRef.value) {
    return
  }
  try {
    await document.exitFullscreen()
  } catch {
    // 用户或浏览器已退出全屏时无需额外处理.
  }
}

async function lockMobileLandscape(): Promise<void> {
  if (isMobile.value === false || props.mobileLandscape === false) {
    return
  }
  if (screen.orientation?.lock === undefined) {
    return
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await screen.orientation.lock('landscape')
      return
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 160))
    }
  }
}

function unlockMobileOrientation(): void {
  try {
    screen.orientation?.unlock?.()
  } catch {
    // unlock 失败不影响退出全屏.
  }
}

async function enterFullscreen(): Promise<void> {
  measuredBodyHeight.value = Math.max(Math.floor((window.visualViewport?.height ?? window.innerHeight) - 150), 260)
  fullscreenActive.value = true
  setBodyFullscreenClass(true)
  await nextTick()
  setupResizeObserver()
  measureBody()
  await requestBrowserFullscreen()
  await waitForNextPaint()
  await lockMobileLandscape()
  emit('fullscreen-change', true)
  emit('layout-change')
}

async function leaveFullscreen(): Promise<void> {
  await exitBrowserFullscreen()
  fullscreenActive.value = false
  setBodyFullscreenClass(false)
  unlockMobileOrientation()
  cleanupResizeObserver()
  await nextTick()
  scheduleMeasure()
  emit('fullscreen-change', false)
  emit('layout-change')
}

function toggleFullscreen(): void {
  if (fullscreenActive.value === true) {
    void leaveFullscreen()
    return
  }
  void enterFullscreen()
}

function onFullscreenChange(): void {
  if (fullscreenActive.value === true && document.fullscreenElement !== rootRef.value) {
    fullscreenActive.value = false
    setBodyFullscreenClass(false)
    unlockMobileOrientation()
    cleanupResizeObserver()
    scheduleMeasure()
    emit('fullscreen-change', false)
    emit('layout-change')
  }
}

function onWindowResize(): void {
  scheduleMeasure()
}

watch(measuredBodyHeight, () => {
  emit('layout-change')
})

onMounted(() => {
  document.addEventListener('fullscreenchange', onFullscreenChange)
  window.addEventListener('resize', onWindowResize)
  window.visualViewport?.addEventListener('resize', onWindowResize)
  scheduleMeasure()
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  window.removeEventListener('resize', onWindowResize)
  window.visualViewport?.removeEventListener('resize', onWindowResize)
  if (measureFrame !== null) {
    window.cancelAnimationFrame(measureFrame)
    measureFrame = null
  }
  cleanupResizeObserver()
  if (fullscreenActive.value === true) {
    unlockMobileOrientation()
    setBodyFullscreenClass(false)
  }
})
</script>

<template>
  <div
    ref="rootRef"
    class="spreadsheet-fullscreen-panel"
    :class="{
      'is-fullscreen': fullscreenActive,
      'is-mobile-landscape': fullscreenActive && isMobile && mobileLandscape,
    }"
  >
    <div class="spreadsheet-fullscreen-viewport">
      <div class="spreadsheet-fullscreen-toolbar">
        <div class="spreadsheet-fullscreen-title">{{ title }}</div>
        <el-button
          size="small"
          :icon="fullscreenActive ? Close : FullScreen"
          @click="toggleFullscreen"
        >
          {{ fullscreenActive ? '退出全屏' : '全屏编辑' }}
        </el-button>
      </div>
      <div v-if="hasActions" class="spreadsheet-fullscreen-actions">
        <slot name="actions" />
      </div>
      <div ref="bodyRef" class="spreadsheet-fullscreen-body">
        <slot :is-fullscreen="fullscreenActive" :table-height="currentTableHeight" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.spreadsheet-fullscreen-panel {
  width: 100%;
  min-width: 0;
}

.spreadsheet-fullscreen-viewport {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.spreadsheet-fullscreen-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.spreadsheet-fullscreen-title {
  min-width: 0;
  color: #12325a;
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spreadsheet-fullscreen-actions {
  min-width: 0;
}

.spreadsheet-fullscreen-body {
  min-width: 0;
}

.spreadsheet-fullscreen-panel.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 7600;
  overflow: hidden;
  background: #ffffff;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-viewport {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  padding: 12px;
  background: #ffffff;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-toolbar {
  flex: 0 0 auto;
  padding-bottom: 8px;
  border-bottom: 1px solid #dce5f0;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions {
  flex: 0 0 auto;
  max-height: 92px;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}

@media (max-width: 767.98px) {
  .spreadsheet-fullscreen-toolbar {
    align-items: stretch;
  }

  .spreadsheet-fullscreen-title {
    align-self: center;
  }
}

</style>

<style>
body.spreadsheet-fullscreen-active .el-message,
body.spreadsheet-fullscreen-active .el-popper {
  z-index: 8001 !important;
}

body.spreadsheet-fullscreen-active .mobile-topbar {
  display: none !important;
}

body.spreadsheet-fullscreen-active .workspace {
  padding-top: 0 !important;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .button-row {
  display: flex !important;
  flex-wrap: nowrap !important;
  align-items: center !important;
  justify-content: flex-start !important;
  gap: 8px !important;
  width: 100% !important;
  min-width: 0 !important;
  margin-bottom: 0 !important;
  padding: 0 0 4px !important;
  overflow-x: auto !important;
  overflow-y: hidden !important;
  -webkit-overflow-scrolling: touch;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-button,
.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select {
  flex: 0 0 auto !important;
  width: auto !important;
  min-width: 88px !important;
  max-width: 180px !important;
  height: 32px !important;
  min-height: 32px !important;
  margin-left: 0 !important;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select .el-select__wrapper {
  box-sizing: border-box !important;
  min-height: 32px !important;
  height: 32px !important;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-button > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-checkbox {
  flex: 0 0 auto !important;
  min-height: 32px !important;
  margin-left: 0 !important;
  margin-right: 0 !important;
  white-space: nowrap;
}

@media (max-width: 767.98px) {
  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-viewport {
    gap: 6px;
    padding: 8px;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-toolbar {
    min-height: 34px;
    padding-bottom: 6px;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions {
    max-height: 42px;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .button-row {
    gap: 6px !important;
    padding-bottom: 2px !important;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-button,
  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select {
    min-width: 84px !important;
    max-width: 132px !important;
    height: 30px !important;
    min-height: 30px !important;
    padding-inline: 10px !important;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select .el-select__wrapper {
    min-height: 30px !important;
    height: 30px !important;
  }

  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select .el-select__selection,
  .spreadsheet-fullscreen-panel.is-fullscreen .spreadsheet-fullscreen-actions .el-select .el-select__selected-item {
    justify-content: center !important;
    text-align: center !important;
  }
}
</style>
