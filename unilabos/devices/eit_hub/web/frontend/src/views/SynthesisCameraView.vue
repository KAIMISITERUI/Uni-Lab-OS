<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { Refresh, VideoCamera } from '@element-plus/icons-vue'
import { type CameraInfo, fetchCameraList } from '../api/synthesis'
import { getErrorMessage } from '../api/http'
import { useViewportMode } from '../composables/useViewportMode'

interface CameraSlot {
  info: CameraInfo
  // 通过自增 token 让 <img> src 改变, 触发浏览器重新发起 MJPEG 连接
  reloadToken: number
  // 当前缩略图是否报错
  failed: boolean
}

type ZoomOrientation = 'auto' | 'landscape' | 'portrait'

const cameras = ref<CameraSlot[]>([])
const loading = ref(false)
const errorText = ref('')
// 控制缩略图是否处于拉流状态, 离开页面时置 false 主动断开
const streamActive = ref(true)
// 当前放大查看的相机, 为 null 时关闭对话框
const zoomedSlot = ref<CameraSlot | null>(null)
const zoomedReloadToken = ref(0)
const zoomedFailed = ref(false)
const zoomOrientation = ref<ZoomOrientation>('auto')
// 弹窗主码流 <img> DOM 引用, 关闭弹窗时显式置空 src 强制释放 MJPEG 连接
const zoomImgEl = ref<HTMLImageElement | null>(null)
const mobileZoomRef = ref<HTMLDivElement | null>(null)
// 缩略图 <img> DOM 引用 Map, 离开页面时显式置空 src 强制释放 sub 流连接
const thumbImgEls = new Map<string, HTMLImageElement>()
const { isMobile } = useViewportMode()

const hasCameras = computed(() => cameras.value.length > 0)
const dialogVisible = computed({
  get: () => zoomedSlot.value !== null,
  set: (value) => {
    if (value === false) {
      zoomedSlot.value = null
    }
  },
})

function buildSrc(url: string, token: number): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}_t=${token}`
}

function clearImgConnection(el: HTMLImageElement | null | undefined): void {
  if (el === null || el === undefined) {
    return
  }
  // 关键: 置空 src 并移除属性, 浏览器会立即 abort MJPEG 请求并释放 socket,
  // 否则 Chromium 在元素 detach 后仍可能保留连接, 累计撑满同源连接数上限,
  // 导致弹窗放大几次后第 N 次点开呈黑屏.
  el.src = ''
  el.removeAttribute('src')
}

function registerThumbEl(id: string, el: HTMLImageElement | null): void {
  if (el === null) {
    thumbImgEls.delete(id)
  } else {
    thumbImgEls.set(id, el)
  }
}

function releaseZoomConnection(): void {
  clearImgConnection(zoomImgEl.value)
}

function releaseAllThumbConnections(): void {
  for (const el of thumbImgEls.values()) {
    clearImgConnection(el)
  }
}

function resetZoomState(): void {
  zoomedReloadToken.value = Date.now()
  zoomedFailed.value = false
  zoomOrientation.value = 'auto'
}

function restoreThumbStreams(): void {
  streamActive.value = true
  for (const slot of cameras.value) {
    slot.failed = false
    slot.reloadToken = Date.now()
  }
}

async function loadCameras(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    const list = await fetchCameraList()
    cameras.value = list.map((info) =>
      reactive<CameraSlot>({ info, reloadToken: Date.now(), failed: false }),
    )
    if (list.length === 0) {
      errorText.value = '未获取到任何摄像头'
    }
  } catch (err) {
    errorText.value = getErrorMessage(err)
    cameras.value = []
  } finally {
    loading.value = false
  }
}

function reloadSingle(slot: CameraSlot): void {
  slot.failed = false
  slot.reloadToken = Date.now()
}

function onThumbError(slot: CameraSlot): void {
  slot.failed = true
}

function onThumbLoad(slot: CameraSlot): void {
  if (slot.failed === true) {
    slot.failed = false
  }
}

function openZoom(slot: CameraSlot): void {
  resetZoomState()
  if (isMobile.value === true) {
    // 手机端放大时独占主码流, 避免缩略图 MJPEG 连接占满同源连接池.
    releaseAllThumbConnections()
    streamActive.value = false
  }
  zoomedSlot.value = slot
  if (isMobile.value === true) {
    void enterMobileZoom()
  }
}

function reloadZoom(): void {
  releaseZoomConnection()
  resetZoomState()
  if (isMobile.value === true) {
    void enterMobileZoom()
  }
}

async function enterMobileZoom(): Promise<void> {
  await nextTick()
  const container = mobileZoomRef.value
  if (container !== null && document.fullscreenElement === null) {
    try {
      await container.requestFullscreen()
    } catch {
      // 浏览器不允许全屏时保持页面内横屏播放器.
    }
  }
  await lockMobileOrientation()
}

async function lockMobileOrientation(): Promise<void> {
  if (zoomOrientation.value === 'auto') {
    return
  }
  try {
    await screen.orientation?.lock?.(zoomOrientation.value)
  } catch {
    // iOS Safari 等环境不支持方向锁定时, 由全屏播放器样式兜住画面.
  }
}

async function exitMobileZoom(): Promise<void> {
  try {
    screen.orientation?.unlock?.()
  } catch {
    // unlock 失败不影响释放视频连接.
  }
  if (document.fullscreenElement !== null) {
    try {
      await document.exitFullscreen()
    } catch {
      // 用户或浏览器已退出全屏时无需额外处理.
    }
  }
}

function onZoomLoad(event: Event): void {
  zoomedFailed.value = false
  const img = event.currentTarget
  if (img instanceof HTMLImageElement === false) {
    return
  }
  if (img.naturalWidth <= 0 || img.naturalHeight <= 0) {
    return
  }
  zoomOrientation.value = img.naturalHeight > img.naturalWidth ? 'portrait' : 'landscape'
  if (isMobile.value === true) {
    void lockMobileOrientation()
  }
}

function onZoomError(): void {
  zoomedFailed.value = true
}

function closeMobileZoom(): void {
  releaseZoomConnection()
  zoomedSlot.value = null
  zoomOrientation.value = 'auto'
  void exitMobileZoom()
  restoreThumbStreams()
}

onMounted(() => {
  streamActive.value = true
  loadCameras()
})

// KeepAlive 缓存场景下, 切回页面时重新激活拉流并刷新 token 让 <img> 重新连接
onActivated(() => {
  streamActive.value = true
  if (cameras.value.length === 0 && errorText.value === '') {
    loadCameras()
  } else {
    for (const slot of cameras.value) {
      slot.failed = false
      slot.reloadToken = Date.now()
    }
  }
})

// 离开页面时主动停止拉流, 同时关闭放大对话框, 避免后台仍占用带宽.
// 先显式清空 <img> 的 src 强制浏览器释放 MJPEG socket,
// 再让 Vue 通过 v-if 移除元素, 避免连接残留撑满同源连接池.
onDeactivated(() => {
  releaseAllThumbConnections()
  releaseZoomConnection()
  streamActive.value = false
  zoomedSlot.value = null
  zoomOrientation.value = 'auto'
  void exitMobileZoom()
})

onBeforeUnmount(() => {
  releaseAllThumbConnections()
  releaseZoomConnection()
  streamActive.value = false
  zoomedSlot.value = null
  zoomOrientation.value = 'auto'
  void exitMobileZoom()
})
</script>

<template>
  <div class="view-stack">
    <section class="panel">
      <div class="panel-title">
        <h2>
          <el-icon class="title-icon"><VideoCamera /></el-icon>
          现场监控
        </h2>
        <div class="panel-actions">
          <span class="hint-text">点击单路画面放大为主码流</span>
          <el-button :icon="Refresh" :loading="loading" @click="loadCameras">
            刷新列表
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="errorText !== ''"
        type="error"
        :title="errorText"
        :closable="false"
        show-icon
      />

      <div v-if="hasCameras" class="camera-grid">
        <div
          v-for="slot in cameras"
          :key="slot.info.id"
          class="camera-card"
        >
          <div class="camera-card-header">
            <span class="camera-id">{{ slot.info.name || slot.info.id }}</span>
            <el-button
              size="small"
              :icon="Refresh"
              text
              type="primary"
              @click.stop="reloadSingle(slot)"
            >
              重连
            </el-button>
          </div>
          <div
            class="camera-frame"
            role="button"
            tabindex="0"
            @click="openZoom(slot)"
            @keydown.enter="openZoom(slot)"
            @keydown.space.prevent="openZoom(slot)"
          >
            <img
              v-if="streamActive"
              :ref="(el) => registerThumbEl(slot.info.id, el as HTMLImageElement | null)"
              :src="buildSrc(slot.info.stream_url_sub, slot.reloadToken)"
              :alt="slot.info.id"
              class="camera-image"
              @error="onThumbError(slot)"
              @load="onThumbLoad(slot)"
            />
            <div v-else class="camera-placeholder">
              已暂停拉流
            </div>
            <div v-if="streamActive && slot.failed" class="camera-overlay">
              <p>画面拉取失败, 请检查 ops_http 与网络</p>
              <el-button type="primary" :icon="Refresh" @click.stop="reloadSingle(slot)">
                重新连接
              </el-button>
            </div>
            <div v-if="streamActive && slot.failed === false" class="camera-zoom-hint">
              点击放大
            </div>
          </div>
        </div>
      </div>

      <el-empty
        v-else-if="loading === false && errorText === ''"
        description="暂无摄像头"
      />
    </section>

    <div
      v-show="isMobile === true && zoomedSlot !== null"
      ref="mobileZoomRef"
      class="mobile-landscape-viewer"
      :class="`is-${zoomOrientation}`"
    >
      <div class="mobile-landscape-shell">
        <div class="mobile-landscape-toolbar">
          <span class="mobile-landscape-title">
            {{ zoomedSlot ? `${zoomedSlot.info.name || zoomedSlot.info.id} - 主码流` : '' }}
          </span>
          <div class="mobile-landscape-actions">
            <el-button size="small" :icon="Refresh" @click="reloadZoom">重连</el-button>
            <el-button size="small" type="primary" @click="closeMobileZoom">关闭</el-button>
          </div>
        </div>
        <div v-if="zoomedSlot !== null" class="mobile-landscape-frame">
          <img
            ref="zoomImgEl"
            :src="buildSrc(zoomedSlot.info.stream_url_main, zoomedReloadToken)"
            :alt="zoomedSlot.info.id"
            class="mobile-landscape-image"
            @error="onZoomError"
            @load="onZoomLoad"
          />
          <div v-if="zoomedFailed" class="camera-overlay">
            <p>主码流拉取失败, 请检查 ops_http 与网络</p>
            <el-button type="primary" :icon="Refresh" @click="reloadZoom">
              重新连接
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      v-if="isMobile === false"
      v-model="dialogVisible"
      :title="zoomedSlot ? `${zoomedSlot.info.name || zoomedSlot.info.id} - 主码流` : ''"
      width="80%"
      align-center
      destroy-on-close
      append-to-body
      class="camera-zoom-dialog"
      @close="releaseZoomConnection"
    >
      <div v-if="zoomedSlot !== null" class="zoom-frame">
        <img
          ref="zoomImgEl"
          :src="buildSrc(zoomedSlot.info.stream_url_main, zoomedReloadToken)"
          :alt="zoomedSlot.info.id"
          class="zoom-image"
          @error="onZoomError"
          @load="onZoomLoad"
        />
        <div v-if="zoomedFailed" class="camera-overlay">
          <p>主码流拉取失败, 请检查 ops_http 与网络</p>
          <el-button type="primary" :icon="Refresh" @click="reloadZoom">
            重新连接
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button :icon="Refresh" @click="reloadZoom">重连</el-button>
        <el-button type="primary" @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.title-icon {
  margin-right: 6px;
  vertical-align: -2px;
  color: #2563eb;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hint-text {
  color: #738196;
  font-size: 13px;
}

.camera-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
  gap: 16px;
  margin-top: 14px;
}

.camera-card {
  display: flex;
  flex-direction: column;
  background: #0f172a;
  border: 1px solid #1f2a44;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.15);
}

.camera-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #111c33;
  color: #e2e8f0;
}

.camera-id {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #f8fafc;
}

.camera-frame {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-in;
  outline: none;
  transition: transform 0.15s ease;
}

.camera-frame:hover .camera-zoom-hint {
  opacity: 1;
}

.camera-frame:focus-visible {
  box-shadow: inset 0 0 0 2px #60a5fa;
}

.camera-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  background: #000;
  pointer-events: none;
}

.camera-placeholder {
  color: #94a3b8;
  font-size: 14px;
}

.camera-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 16px;
  background: rgba(15, 23, 42, 0.78);
  color: #e2e8f0;
  text-align: center;
}

.camera-overlay p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
}

.camera-zoom-hint {
  position: absolute;
  right: 10px;
  bottom: 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.65);
  color: #e2e8f0;
  font-size: 12px;
  letter-spacing: 0.5px;
  opacity: 0;
  transition: opacity 0.15s ease;
  pointer-events: none;
}

.zoom-frame {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.zoom-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}

.mobile-landscape-viewer {
  position: fixed;
  inset: 0;
  z-index: 7000;
  overflow: hidden;
  background: #000000;
}

.mobile-landscape-shell {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: #000000;
}

.mobile-landscape-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 48px;
  padding: 6px 10px;
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.92);
}

.mobile-landscape-title {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-landscape-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.mobile-landscape-frame {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  align-items: center;
  justify-content: center;
  background: #000000;
}

.mobile-landscape-image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000000;
}

@media (max-width: 767.98px) and (orientation: portrait) {
  .mobile-landscape-viewer.is-landscape .mobile-landscape-shell {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 100dvh;
    height: 100dvw;
    transform: translate(-50%, -50%) rotate(90deg);
    transform-origin: center center;
  }
}

@media (max-width: 767.98px) {
  .camera-zoom-dialog :deep(.el-dialog__body) {
    display: flex;
    align-items: center;
  }

  .zoom-frame {
    aspect-ratio: auto;
    height: min(48dvh, 360px);
  }

  .zoom-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }

  .panel-actions {
    flex-wrap: wrap;
    gap: 8px;
  }

  .hint-text {
    font-size: 12px;
  }
}
</style>
