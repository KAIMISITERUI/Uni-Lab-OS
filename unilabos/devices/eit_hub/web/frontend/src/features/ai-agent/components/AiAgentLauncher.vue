<script setup lang="ts">
// AI 助手浮动入口: 右下角圆形按钮 + 抽屉聊天面板.
// 跨路由不卸载, v-show 切换以保留输入草稿和滚动位置.
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  ChatDotRound,
  Close,
  Expand,
  Loading,
  Plus,
  Refresh,
  Top,
} from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { AI_AGENT_MODEL_OPTIONS, type AiAgentModelId } from '../types'
import { useAiAgent } from '../state/useAiAgent'

const ai = useAiAgent()

// 图钉图标组件: 钉住时显示填充直立图钉, 未钉住时显示描边图钉, 与 el-icon 兼容
const PinIcon = defineComponent({
  name: 'PinIcon',
  props: {
    pinned: { type: Boolean, default: false },
  },
  setup(props) {
    return () =>
      h(
        'svg',
        {
          viewBox: '0 0 24 24',
          fill: 'currentColor',
          xmlns: 'http://www.w3.org/2000/svg',
          'aria-hidden': 'true',
        },
        [
          h('path', {
            d:
              props.pinned === true
                ? 'M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z'
                : 'M14 4v5c0 1.12.37 2.16 1 3H9c.65-.86 1-1.9 1-3V4h4m3-2H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3V4h1c.55 0 1-.45 1-1s-.45-1-1-1z',
          }),
        ],
      )
  },
})

const inputText = ref('')
const sessionMenuOpen = ref(false)
const messageScroll = ref<HTMLDivElement | null>(null)
const drawerReady = ref(false)
const drawerInteracting = ref(false)
const showToolCalls = ref(true)
// 与 useViewportMode 的 (max-width: 767.98px) 互补, 768 以上视为桌面布局.
// 桌面布局下保留侧栏/悬浮窗双模式; 768 以下走"底部全屏 sheet"模式, 入口由 App.vue 的 mobile-topbar 接管, 不再渲染右下角 FAB.
const DESKTOP_QUERY = '(min-width: 768px)'
const isDesktopLayout = ref(
  typeof window !== 'undefined' ? window.matchMedia(DESKTOP_QUERY).matches : false,
)
const panelMode = ref<'side' | 'window'>('side')

interface DrawerRect {
  left: number
  top: number
  width: number
  height: number
}

type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

interface DrawerInteraction {
  kind: 'move' | 'resize'
  pointerId: number
  startX: number
  startY: number
  startRect: DrawerRect
  direction: ResizeDirection | null
}

interface SidePanelResizeInteraction {
  pointerId: number
  startX: number
  startWidth: number
}

interface FabDragInteraction {
  pointerId: number
  startX: number
  startY: number
  startTop: number
  moved: boolean
}

const VIEWPORT_MARGIN = 16
const DEFAULT_DRAWER_WIDTH = 400
const DEFAULT_DRAWER_HEIGHT = 640
const DEFAULT_SIDE_PANEL_WIDTH = 420
const MIN_SIDE_PANEL_WIDTH = 360
const MAX_SIDE_PANEL_WIDTH = 760
const FAB_SIZE = 56
const FAB_DEFAULT_OFFSET = 24
const FAB_DRAG_THRESHOLD = 4

const drawerRect = reactive<DrawerRect>({
  left: 0,
  top: 0,
  width: DEFAULT_DRAWER_WIDTH,
  height: DEFAULT_DRAWER_HEIGHT,
})
const sidePanelWidth = ref(DEFAULT_SIDE_PANEL_WIDTH)
const fabPosition = reactive({
  left: 0,
  top: 0,
})
const fabReady = ref(false)
const fabDragging = ref(false)

let activeInteraction: DrawerInteraction | null = null
let activeSidePanelResize: SidePanelResizeInteraction | null = null
let activeFabDrag: FabDragInteraction | null = null
let suppressNextFabClick = false
let desktopQuery: MediaQueryList | null = null

marked.setOptions({ gfm: true, breaks: true })

function renderMarkdown(content: string): string {
  if ((content || '').trim() === '') {
    return ''
  }
  const html = marked.parse(content, { async: false }) as string
  return DOMPurify.sanitize(html)
}

const visibleMessages = computed(() => {
  return ai.state.messages.filter((row) => {
    if (row.role === 'system') {
      return false
    }
    if (row.role === 'tool' && showToolCalls.value === false) {
      return false
    }
    return true
  })
})

const drawerStyle = computed(() => {
  return {
    left: `${drawerRect.left}px`,
    top: `${drawerRect.top}px`,
    width: `${drawerRect.width}px`,
    height: `${drawerRect.height}px`,
    visibility: drawerReady.value === true ? 'visible' : 'hidden',
  }
})

const activeDrawerStyle = computed(() => {
  if (isSidePanel.value === true) {
    return sidePanelStyle.value
  }
  return drawerStyle.value
})

const sidePanelStyle = computed(() => {
  return {
    width: `${sidePanelWidth.value}px`,
    visibility: 'visible',
  }
})

const fabStyle = computed(() => {
  return {
    left: `${fabPosition.left}px`,
    top: `${fabPosition.top}px`,
    visibility: fabReady.value === true ? 'visible' : 'hidden',
  }
})

const isSidePanel = computed(() => {
  return isDesktopLayout.value === true && panelMode.value === 'side'
})

const isFloatingPanel = computed(() => {
  return isDesktopLayout.value === false || panelMode.value === 'window'
})

const panelModeToggleTip = computed(() => {
  if (isSidePanel.value === true) {
    return '切换为悬浮小窗'
  }
  return '切换为右侧栏'
})

function clamp(value: number, minValue: number, maxValue: number): number {
  if (maxValue < minValue) {
    return minValue
  }
  return Math.min(Math.max(value, minValue), maxValue)
}

function getViewportWidth(): number {
  return window.innerWidth
}

function getViewportHeight(): number {
  return window.innerHeight
}

function getMinDrawerWidth(): number {
  return Math.max(160, Math.min(360, getViewportWidth() - VIEWPORT_MARGIN * 2))
}

function getMinDrawerHeight(): number {
  return Math.max(260, Math.min(420, getViewportHeight() - VIEWPORT_MARGIN * 2))
}

function getMaxDrawerWidth(): number {
  return Math.max(getMinDrawerWidth(), getViewportWidth() - VIEWPORT_MARGIN * 2)
}

function getMaxDrawerHeight(): number {
  return Math.max(getMinDrawerHeight(), getViewportHeight() - VIEWPORT_MARGIN * 2)
}

function getMaxSidePanelWidth(): number {
  return Math.max(MIN_SIDE_PANEL_WIDTH, Math.min(MAX_SIDE_PANEL_WIDTH, getViewportWidth() - VIEWPORT_MARGIN * 2))
}

function normalizeSidePanelWidth(width: number): number {
  return clamp(width, MIN_SIDE_PANEL_WIDTH, getMaxSidePanelWidth())
}

function applySidePanelWidth(width: number): void {
  sidePanelWidth.value = normalizeSidePanelWidth(width)
}

function getFabRightAlignedLeft(): number {
  return getViewportWidth() - FAB_SIZE - FAB_DEFAULT_OFFSET
}

function normalizeFabPosition(top: number): { left: number; top: number } {
  return {
    left: clamp(getFabRightAlignedLeft(), VIEWPORT_MARGIN, getViewportWidth() - FAB_SIZE - VIEWPORT_MARGIN),
    top: clamp(top, VIEWPORT_MARGIN, getViewportHeight() - FAB_SIZE - VIEWPORT_MARGIN),
  }
}

function applyFabPosition(top: number): void {
  const normalized = normalizeFabPosition(top)
  fabPosition.left = normalized.left
  fabPosition.top = normalized.top
}

function resetFabPositionToDefault(): void {
  applyFabPosition(getViewportHeight() - FAB_SIZE - FAB_DEFAULT_OFFSET)
}

function initFabPosition(): void {
  resetFabPositionToDefault()
  fabReady.value = true
}

function normalizeDrawerRect(rect: DrawerRect): DrawerRect {
  const width = clamp(rect.width, getMinDrawerWidth(), getMaxDrawerWidth())
  const height = clamp(rect.height, getMinDrawerHeight(), getMaxDrawerHeight())
  return {
    left: clamp(rect.left, VIEWPORT_MARGIN, getViewportWidth() - width - VIEWPORT_MARGIN),
    top: clamp(rect.top, VIEWPORT_MARGIN, getViewportHeight() - height - VIEWPORT_MARGIN),
    width,
    height,
  }
}

function applyDrawerRect(rect: DrawerRect): void {
  const normalized = normalizeDrawerRect(rect)
  drawerRect.left = normalized.left
  drawerRect.top = normalized.top
  drawerRect.width = normalized.width
  drawerRect.height = normalized.height
}

function resetDrawerRectToDefault(): void {
  const width = Math.min(DEFAULT_DRAWER_WIDTH, getMaxDrawerWidth())
  const height = Math.min(DEFAULT_DRAWER_HEIGHT, getMaxDrawerHeight())
  applyDrawerRect({
    left: getViewportWidth() - width - 24,
    top: getViewportHeight() - height - 24,
    width,
    height,
  })
  drawerReady.value = true
}

function onViewportResize(): void {
  applyFabPosition(fabPosition.top)
  if (isSidePanel.value === true) {
    applySidePanelWidth(sidePanelWidth.value)
    return
  }
  if (drawerReady.value === false) {
    resetDrawerRectToDefault()
    return
  }
  applyDrawerRect({ ...drawerRect })
}

function stopDrawerInteraction(): void {
  if (activeInteraction === null) {
    return
  }
  window.removeEventListener('pointermove', onDrawerPointerMove)
  window.removeEventListener('pointerup', onDrawerPointerUp)
  window.removeEventListener('pointercancel', onDrawerPointerUp)
  activeInteraction = null
  drawerInteracting.value = false
}

function stopSidePanelResize(): void {
  if (activeSidePanelResize === null) {
    return
  }
  window.removeEventListener('pointermove', onSidePanelResizeMove)
  window.removeEventListener('pointerup', onSidePanelResizeEnd)
  window.removeEventListener('pointercancel', onSidePanelResizeEnd)
  activeSidePanelResize = null
  drawerInteracting.value = false
}

function stopFabDrag(): void {
  if (activeFabDrag === null) {
    return
  }
  window.removeEventListener('pointermove', onFabPointerMove)
  window.removeEventListener('pointerup', onFabPointerUp)
  window.removeEventListener('pointercancel', onFabPointerUp)
  activeFabDrag = null
  fabDragging.value = false
}

function onFabPointerDown(event: PointerEvent): void {
  if (event.button !== 0) {
    return
  }
  event.preventDefault()
  activeFabDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startTop: fabPosition.top,
    moved: false,
  }
  fabDragging.value = true
  window.addEventListener('pointermove', onFabPointerMove)
  window.addEventListener('pointerup', onFabPointerUp)
  window.addEventListener('pointercancel', onFabPointerUp)
}

function onFabPointerMove(event: PointerEvent): void {
  if (activeFabDrag === null || event.pointerId !== activeFabDrag.pointerId) {
    return
  }
  event.preventDefault()
  const deltaX = event.clientX - activeFabDrag.startX
  const deltaY = event.clientY - activeFabDrag.startY
  if (Math.abs(deltaX) > FAB_DRAG_THRESHOLD || Math.abs(deltaY) > FAB_DRAG_THRESHOLD) {
    activeFabDrag.moved = true
  }
  applyFabPosition(activeFabDrag.startTop + deltaY)
}

function onFabPointerUp(event: PointerEvent): void {
  if (activeFabDrag === null || event.pointerId !== activeFabDrag.pointerId) {
    return
  }
  suppressNextFabClick = activeFabDrag.moved
  if (activeFabDrag.moved === true) {
    window.setTimeout(() => {
      suppressNextFabClick = false
    }, 0)
  } else {
    applyFabPosition(activeFabDrag.startTop)
  }
  stopFabDrag()
}

function onFabClick(event: MouseEvent): void {
  if (suppressNextFabClick === true) {
    suppressNextFabClick = false
    event.preventDefault()
    event.stopPropagation()
    return
  }
  ai.open()
}

function startDrawerInteraction(
  event: PointerEvent,
  kind: 'move' | 'resize',
  direction: ResizeDirection | null,
): void {
  if (event.button !== 0) {
    return
  }
  event.preventDefault()
  activeInteraction = {
    kind,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startRect: { ...drawerRect },
    direction,
  }
  drawerInteracting.value = true
  window.addEventListener('pointermove', onDrawerPointerMove)
  window.addEventListener('pointerup', onDrawerPointerUp)
  window.addEventListener('pointercancel', onDrawerPointerUp)
}

function onDrawerMoveStart(event: PointerEvent): void {
  const target = event.target
  if (target instanceof HTMLElement && target.closest('.ai-header-actions') !== null) {
    return
  }
  startDrawerInteraction(event, 'move', null)
}

function onDrawerResizeStart(event: PointerEvent, direction: ResizeDirection): void {
  if (isSidePanel.value === true) {
    return
  }
  startDrawerInteraction(event, 'resize', direction)
}

function onHeaderPointerDown(event: PointerEvent): void {
  if (isSidePanel.value === true) {
    return
  }
  onDrawerMoveStart(event)
}

function onSidePanelResizeStart(event: PointerEvent): void {
  if (event.button !== 0) {
    return
  }
  event.preventDefault()
  stopDrawerInteraction()
  activeSidePanelResize = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startWidth: sidePanelWidth.value,
  }
  drawerInteracting.value = true
  window.addEventListener('pointermove', onSidePanelResizeMove)
  window.addEventListener('pointerup', onSidePanelResizeEnd)
  window.addEventListener('pointercancel', onSidePanelResizeEnd)
}

function onSidePanelResizeMove(event: PointerEvent): void {
  if (activeSidePanelResize === null || event.pointerId !== activeSidePanelResize.pointerId) {
    return
  }
  const deltaX = activeSidePanelResize.startX - event.clientX
  applySidePanelWidth(activeSidePanelResize.startWidth + deltaX)
}

function onSidePanelResizeEnd(event: PointerEvent): void {
  if (activeSidePanelResize === null || event.pointerId !== activeSidePanelResize.pointerId) {
    return
  }
  stopSidePanelResize()
}

function buildMovedRect(interaction: DrawerInteraction, event: PointerEvent): DrawerRect {
  const deltaX = event.clientX - interaction.startX
  const deltaY = event.clientY - interaction.startY
  return {
    left: interaction.startRect.left + deltaX,
    top: interaction.startRect.top + deltaY,
    width: interaction.startRect.width,
    height: interaction.startRect.height,
  }
}

function buildResizedRect(interaction: DrawerInteraction, event: PointerEvent): DrawerRect {
  const direction = interaction.direction
  if (direction === null) {
    return { ...interaction.startRect }
  }

  const deltaX = event.clientX - interaction.startX
  const deltaY = event.clientY - interaction.startY
  const startRight = interaction.startRect.left + interaction.startRect.width
  const startBottom = interaction.startRect.top + interaction.startRect.height
  let left = interaction.startRect.left
  let top = interaction.startRect.top
  let width = interaction.startRect.width
  let height = interaction.startRect.height

  if (direction.includes('e') === true) {
    const maxWidth = Math.min(getMaxDrawerWidth(), getViewportWidth() - VIEWPORT_MARGIN - interaction.startRect.left)
    width = clamp(interaction.startRect.width + deltaX, getMinDrawerWidth(), maxWidth)
  }
  if (direction.includes('w') === true) {
    const maxWidth = Math.min(getMaxDrawerWidth(), startRight - VIEWPORT_MARGIN)
    width = clamp(interaction.startRect.width - deltaX, getMinDrawerWidth(), maxWidth)
    left = startRight - width
  }
  if (direction.includes('s') === true) {
    const maxHeight = Math.min(getMaxDrawerHeight(), getViewportHeight() - VIEWPORT_MARGIN - interaction.startRect.top)
    height = clamp(interaction.startRect.height + deltaY, getMinDrawerHeight(), maxHeight)
  }
  if (direction.includes('n') === true) {
    const maxHeight = Math.min(getMaxDrawerHeight(), startBottom - VIEWPORT_MARGIN)
    height = clamp(interaction.startRect.height - deltaY, getMinDrawerHeight(), maxHeight)
    top = startBottom - height
  }

  return { left, top, width, height }
}

function onDrawerPointerMove(event: PointerEvent): void {
  if (activeInteraction === null || event.pointerId !== activeInteraction.pointerId) {
    return
  }
  if (activeInteraction.kind === 'move') {
    applyDrawerRect(buildMovedRect(activeInteraction, event))
    return
  }
  applyDrawerRect(buildResizedRect(activeInteraction, event))
}

function onDrawerPointerUp(event: PointerEvent): void {
  if (activeInteraction === null || event.pointerId !== activeInteraction.pointerId) {
    return
  }
  stopDrawerInteraction()
}

async function scrollToBottom() {
  await nextTick()
  if (messageScroll.value !== null) {
    messageScroll.value.scrollTop = messageScroll.value.scrollHeight
  }
}

watch(
  () => ai.state.messages.length,
  () => {
    void scrollToBottom()
  },
)
watch(
  () => ai.state.messages[ai.state.messages.length - 1]?.content,
  () => {
    void scrollToBottom()
  },
)
watch(
  () => ai.state.open,
  (now) => {
    if (now === true) {
      void scrollToBottom()
    }
  },
)

function syncDesktopLayout(matches: boolean): void {
  isDesktopLayout.value = matches
  if (isSidePanel.value === true) {
    stopDrawerInteraction()
    stopSidePanelResize()
    applySidePanelWidth(sidePanelWidth.value)
    drawerReady.value = true
    return
  }
  stopSidePanelResize()
  resetDrawerRectToDefault()
}

function onDesktopQueryChange(event: MediaQueryListEvent): void {
  syncDesktopLayout(event.matches)
}

// 点击助手以外区域时自动隐藏面板; 钉住状态下保持打开
// 用 pointerdown (capture) 是为了在 Element Plus 内部 popper 调用 stopPropagation 之前判断归属
function onDocumentPointerDown(event: PointerEvent): void {
  if (ai.state.open === false || ai.state.pinned === true) {
    return
  }
  const target = event.target
  if (target instanceof Element === false) {
    return
  }
  // 命中助手自身, 不隐藏
  if (target.closest('.ai-launcher-root') !== null) {
    return
  }
  // 手机端顶部栏的 AI 入口按钮承担 toggle 语义, 它 click 后 App.vue 会调用 ai.toggle();
  // 这里若再 close 一次会和 toggle 形成 close → open 的连续翻转, 面板看似不会关闭. 直接放行.
  if (target.closest('.mobile-topbar') !== null) {
    return
  }
  // Element Plus 浮层 (tooltip / 下拉 / MessageBox / Message / Overlay) 挂载在 body 上,
  // 但这些是助手内部按钮触发的 UI, 点击不应触发隐藏
  if (
    target.closest('.el-popper') !== null ||
    target.closest('.el-overlay') !== null ||
    target.closest('.el-message-box') !== null ||
    target.closest('.el-message') !== null
  ) {
    return
  }
  ai.close()
}

onMounted(() => {
  initFabPosition()
  desktopQuery = window.matchMedia(DESKTOP_QUERY)
  syncDesktopLayout(desktopQuery.matches)
  if (typeof desktopQuery.addEventListener === 'function') {
    desktopQuery.addEventListener('change', onDesktopQueryChange)
  } else {
    desktopQuery.addListener(onDesktopQueryChange)
  }
  window.addEventListener('resize', onViewportResize)
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  void ai.refreshRecentSessions()
  void ai.refreshConfig()
})

onBeforeUnmount(() => {
  stopFabDrag()
  stopDrawerInteraction()
  stopSidePanelResize()
  if (desktopQuery !== null) {
    if (typeof desktopQuery.removeEventListener === 'function') {
      desktopQuery.removeEventListener('change', onDesktopQueryChange)
    } else {
      desktopQuery.removeListener(onDesktopQueryChange)
    }
  }
  window.removeEventListener('resize', onViewportResize)
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

async function onSend() {
  const text = inputText.value
  inputText.value = ''
  await ai.sendMessage(text)
}

function onPrimaryInputAction(): void {
  if (ai.state.sending === true) {
    ai.stopStreaming()
    return
  }
  void onSend()
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key === 'Enter' && event.shiftKey === false && event.isComposing === false) {
    event.preventDefault()
    void onSend()
  }
}

async function onConfirmPending() {
  await ai.confirmPending()
}

async function onRejectPending() {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请说明拒绝原因 (可空):', '拒绝执行', {
      inputType: 'textarea',
      confirmButtonText: '提交拒绝',
      cancelButtonText: '取消',
      inputPlaceholder: '比如: 今天还没做完, 明天再标记.',
    })
    reason = (result.value || '').trim()
  } catch (_err) {
    return
  }
  await ai.rejectPending(reason)
}

async function onSwitchSession(sessionId: string) {
  sessionMenuOpen.value = false
  await ai.openWith(sessionId)
}

async function onNewSession() {
  sessionMenuOpen.value = false
  await ai.newSession()
}

function switchPanelMode(nextMode: 'side' | 'window'): void {
  if (panelMode.value === nextMode) {
    return
  }
  panelMode.value = nextMode
  sessionMenuOpen.value = false
  if (nextMode === 'side') {
    stopDrawerInteraction()
    stopSidePanelResize()
    applySidePanelWidth(sidePanelWidth.value)
    drawerReady.value = true
    void scrollToBottom()
    return
  }
  stopSidePanelResize()
  resetDrawerRectToDefault()
  void scrollToBottom()
}

function togglePanelMode(): void {
  if (isSidePanel.value === true) {
    switchPanelMode('window')
    return
  }
  switchPanelMode('side')
}

function onClosePanel() {
  sessionMenuOpen.value = false
  ai.close()
}

function formatTime(text: string | null): string {
  if (text === null || text === '') {
    return ''
  }
  try {
    return new Date(text).toLocaleString('zh-CN', { hour12: false })
  } catch (_err) {
    return text
  }
}

function getToolDisplayLines(payload: Record<string, unknown> | null): string[] {
  if (payload === null) {
    return []
  }
  try {
    return JSON.stringify(payload, null, 2).split('\n')
  } catch (_err) {
    return []
  }
}

function dismissError() {
  ai.state.error = null
  ElMessage.info('已忽略错误提示')
}

function getModelLabel(modelId: string): string {
  const option = AI_AGENT_MODEL_OPTIONS.find((item) => item.value === modelId)
  return option?.label ?? modelId
}

async function onSwitchModel(modelId: AiAgentModelId): Promise<void> {
  if (ai.state.sending === true) {
    ElMessage.warning('模型生成中, 请等待本轮对话结束后再切换.')
    return
  }
  if (ai.state.pending !== null) {
    ElMessage.warning('请先处理待确认的写操作, 再切换模型.')
    return
  }
  try {
    await ai.switchModel(modelId)
    ElMessage.success(`已切换为${getModelLabel(modelId)}模式, 下一次对话生效.`)
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}
</script>

<template>
  <div
    class="ai-launcher-root"
    :class="{
      'ai-launcher-desktop': isDesktopLayout === true,
      'ai-launcher-mobile': isDesktopLayout === false,
      'ai-launcher-side-mode': isSidePanel === true,
      'ai-launcher-window-mode': isFloatingPanel === true,
    }"
  >
    <!-- 浮动按钮: 关闭状态始终使用右下角入口. -->
    <button
      v-if="ai.state.open === false"
      class="ai-fab"
      :class="{ 'ai-fab-dragging': fabDragging === true }"
      :style="fabStyle"
      type="button"
      aria-label="打开 AI 助手"
      @pointerdown="onFabPointerDown"
      @click="onFabClick"
    >
      <el-icon><ChatDotRound /></el-icon>
    </button>

    <!-- 抽屉: v-show 而非 v-if, 保留状态 -->
    <section
      v-show="ai.state.open === true"
      class="ai-drawer"
      :class="{
        'ai-drawer-interacting': drawerInteracting,
        'ai-drawer-side': isSidePanel === true,
        'ai-drawer-floating': isFloatingPanel === true,
      }"
      :style="activeDrawerStyle"
      role="dialog"
      aria-label="AI 助手"
    >
      <header class="ai-drawer-header" @pointerdown="onHeaderPointerDown">
        <div class="ai-header-title">
          <el-icon class="ai-header-icon"><ChatDotRound /></el-icon>
          <div class="ai-header-meta">
            <div class="ai-header-name">AI 助手</div>
            <div class="ai-header-sub">DeepSeek · {{ ai.state.sessionId === null ? '新会话' : ai.state.sessionId.slice(0, 8) }}</div>
          </div>
        </div>
        <div class="ai-header-actions" @pointerdown.stop>
          <el-tooltip
            :content="ai.state.pinned === true ? '取消固定 (允许点击外部隐藏)' : '固定面板 (始终悬浮)'"
            placement="top"
          >
            <button
              type="button"
              class="ai-icon-btn ai-pin-btn"
              :class="{ 'ai-pin-btn-active': ai.state.pinned === true }"
              :aria-pressed="ai.state.pinned === true"
              @click="ai.togglePin"
            >
              <el-icon><PinIcon :pinned="ai.state.pinned" /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="切换会话" placement="top">
            <button
              type="button"
              class="ai-icon-btn"
              :aria-expanded="sessionMenuOpen"
              @click="sessionMenuOpen = !sessionMenuOpen"
            >
              <el-icon><component :is="sessionMenuOpen ? ArrowUp : ArrowDown" /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="新建会话" placement="top">
            <button type="button" class="ai-icon-btn" @click="onNewSession">
              <el-icon><Plus /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="刷新当前会话" placement="top">
            <button
              type="button"
              class="ai-icon-btn"
              :disabled="ai.state.sessionId === null || ai.state.sending"
              @click="ai.refreshCurrentSession"
            >
              <el-icon><Refresh /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip v-if="isDesktopLayout === true" :content="panelModeToggleTip" placement="top">
            <button type="button" class="ai-icon-btn" @click="togglePanelMode">
              <el-icon><Expand /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip :content="isDesktopLayout === true ? '收起' : '关闭'" placement="top">
            <button type="button" class="ai-icon-btn ai-icon-btn-close" @click="onClosePanel">
              <el-icon><Close /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </header>

      <!-- 会话切换下拉 -->
      <div v-if="sessionMenuOpen === true" class="ai-session-menu">
        <div class="ai-session-menu-title">最近 5 个会话</div>
        <div v-if="ai.state.recentLoading === true" class="ai-session-menu-empty">
          <el-icon class="is-loading"><Loading /></el-icon>
          加载中...
        </div>
        <div v-else-if="ai.state.recentSessions.length === 0" class="ai-session-menu-empty">
          暂无会话
        </div>
        <div
          v-for="item in ai.state.recentSessions"
          :key="item.session_id"
          class="ai-session-menu-item"
          :class="{ 'ai-session-menu-active': item.session_id === ai.state.sessionId }"
          @click="onSwitchSession(item.session_id)"
        >
          <div class="ai-session-menu-row">
            <span class="ai-session-menu-name">{{ item.title }}</span>
          </div>
          <div class="ai-session-menu-time">{{ formatTime(item.last_at) }}</div>
        </div>
      </div>

      <!-- 错误条 -->
      <div v-if="ai.state.error !== null" class="ai-error">
        <span>{{ ai.state.error }}</span>
        <button type="button" class="ai-icon-btn" @click="dismissError">
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <!-- 消息区 -->
      <main ref="messageScroll" class="ai-drawer-body">
        <div v-if="visibleMessages.length === 0" class="ai-empty">
          <el-icon class="ai-empty-icon"><ChatDotRound /></el-icon>
          <div class="ai-empty-title">你好, 我是 EIT 助手</div>
          <div class="ai-empty-sub">
            可以帮你查运维记录、AGV 状态、设备连通性、化学品库, 也可以协助提交运维记录 (写操作需你确认).
          </div>
        </div>

        <template v-for="row in visibleMessages" :key="row.local_id">
          <div v-if="row.role === 'user'" class="ai-msg ai-msg-user">
            <div class="ai-msg-bubble">{{ row.content }}</div>
          </div>
          <div v-else-if="row.role === 'assistant'" class="ai-msg ai-msg-assistant">
            <div class="ai-msg-bubble">
              <div
                v-if="row.content !== ''"
                class="ai-md-body"
                v-html="renderMarkdown(row.content)"
              ></div>
              <div v-if="row.status === 'streaming'" class="ai-cursor">▌</div>
            </div>
          </div>
          <div v-else-if="row.role === 'tool'" class="ai-msg ai-msg-tool">
            <div
              class="ai-tool-card"
              :class="{
                'ai-tool-card-pending': row.status === 'pending_confirm',
                'ai-tool-card-rejected': row.status === 'rejected',
              }"
            >
              <div class="ai-tool-card-header">
                <span class="ai-tool-card-name">
                  工具: {{ row.pending_tool_name || row.tool_call_id }}
                </span>
                <span v-if="row.status === 'streaming'" class="ai-tool-card-status">执行中…</span>
                <span v-else-if="row.status === 'pending_confirm'" class="ai-tool-card-status">待确认</span>
                <span v-else-if="row.status === 'rejected'" class="ai-tool-card-status">已拒绝</span>
                <span v-else class="ai-tool-card-status ai-tool-card-status-ok">已执行</span>
              </div>
              <div v-if="row.pending_tool_args" class="ai-tool-card-section">
                <div class="ai-tool-card-section-title">参数</div>
                <pre class="ai-tool-card-pre">{{ JSON.stringify(row.pending_tool_args, null, 2) }}</pre>
              </div>
              <div v-if="row.status === 'committed' || row.status === 'rejected'" class="ai-tool-card-section">
                <div class="ai-tool-card-section-title">结果</div>
                <pre class="ai-tool-card-pre">
{{ row.display_payload ? getToolDisplayLines(row.display_payload).join('\n') : row.content }}</pre>
              </div>
            </div>
          </div>
        </template>

        <!-- 待确认的控制类工具卡片 (置顶醒目) -->
        <div v-if="ai.state.pending !== null" class="ai-pending-card">
          <div class="ai-pending-title">⚠ 写操作待确认</div>
          <div class="ai-pending-meta">
            <div><strong>工具:</strong> {{ ai.state.pending.name }}</div>
            <div v-if="ai.state.pending.description !== ''">
              <strong>说明:</strong> {{ ai.state.pending.description }}
            </div>
          </div>
          <div class="ai-pending-section">
            <div class="ai-tool-card-section-title">参数 (将提交至后端)</div>
            <pre class="ai-tool-card-pre">{{ JSON.stringify(ai.state.pending.arguments, null, 2) }}</pre>
          </div>
          <div class="ai-pending-actions">
            <el-button type="primary" :loading="ai.state.sending" @click="onConfirmPending">
              确认执行
            </el-button>
            <el-button :disabled="ai.state.sending" @click="onRejectPending">拒绝并说明</el-button>
          </div>
        </div>
      </main>

      <!-- 输入区 -->
      <footer class="ai-drawer-footer">
        <textarea
          v-model="inputText"
          class="ai-input"
          rows="3"
          :disabled="ai.state.sending || ai.state.pending !== null"
          :placeholder="
            ai.state.pending !== null
              ? '请先处理待确认的写操作'
              : '输入消息 (Shift+Enter 换行, Enter 发送)'
          "
          @keydown="onKeyDown"
        ></textarea>
        <div class="ai-input-bar">
          <span class="ai-input-tip">
            <span v-if="ai.state.sending"><el-icon class="is-loading"><Loading /></el-icon> 模型生成中...</span>
            <span v-else-if="ai.state.pending !== null">写操作等待你的判断</span>
            <label v-else class="ai-tool-toggle">
              <input v-model="showToolCalls" type="checkbox" />
              <span>展示工具调用</span>
            </label>
          </span>
          <div class="ai-input-actions">
            <div class="ai-model-switch" aria-label="模型模式">
              <button
                v-for="option in AI_AGENT_MODEL_OPTIONS"
                :key="option.value"
                type="button"
                class="ai-model-option"
                :class="{ 'ai-model-option-active': ai.state.modelId === option.value }"
                :disabled="ai.state.sending || ai.state.pending !== null || ai.state.modelSaving"
                @click="onSwitchModel(option.value)"
              >
                <el-icon v-if="ai.state.modelSaving === true && ai.state.modelId !== option.value" class="is-loading">
                  <Loading />
                </el-icon>
                <span>{{ option.label }}</span>
              </button>
            </div>
            <el-button
              class="ai-send-button"
              type="primary"
              :disabled="ai.state.sending === false && (ai.state.pending !== null || inputText.trim() === '')"
              :aria-label="ai.state.sending === true ? '停止生成' : '发送消息'"
              @click="onPrimaryInputAction"
            >
              <span v-if="ai.state.sending === true" class="ai-stop-square" aria-hidden="true"></span>
              <el-icon v-else><Top /></el-icon>
            </el-button>
          </div>
        </div>
      </footer>

      <div
        v-if="isSidePanel === true"
        class="ai-side-resize-handle"
        aria-hidden="true"
        @pointerdown="onSidePanelResizeStart"
      ></div>

      <template v-if="isFloatingPanel === true">
        <div class="ai-resize-handle ai-resize-handle-n" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'n')"></div>
        <div class="ai-resize-handle ai-resize-handle-s" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 's')"></div>
        <div class="ai-resize-handle ai-resize-handle-e" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'e')"></div>
        <div class="ai-resize-handle ai-resize-handle-w" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'w')"></div>
        <div class="ai-resize-handle ai-resize-handle-ne" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'ne')"></div>
        <div class="ai-resize-handle ai-resize-handle-nw" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'nw')"></div>
        <div class="ai-resize-handle ai-resize-handle-se" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'se')"></div>
        <div class="ai-resize-handle ai-resize-handle-sw" aria-hidden="true" @pointerdown="onDrawerResizeStart($event, 'sw')"></div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.ai-launcher-root {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 2000;
}

.ai-fab,
.ai-drawer {
  pointer-events: auto;
}

/* ===== 浮动按钮 ===== */
.ai-fab {
  position: absolute;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  color: #ffffff;
  background: #1a5fa8;
  border: 0;
  border-radius: 28px;
  box-shadow: 0 12px 28px rgba(18, 50, 90, 0.32);
  cursor: grab;
  transition: transform 0.18s ease, background 0.18s ease;
  touch-action: none;
  user-select: none;
}

.ai-fab:hover {
  background: #174f8a;
  transform: translateY(-2px);
}

.ai-fab:active {
  transform: translateY(0);
}

.ai-fab-dragging {
  cursor: grabbing;
  transition: background 0.18s ease;
}

/* ===== 抽屉 ===== */
.ai-drawer {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 12px;
  box-shadow: 0 20px 48px rgba(18, 50, 90, 0.24);
  overflow: hidden;
}

.ai-drawer-interacting {
  user-select: none;
}

.ai-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: #ffffff;
  color: #12325a;
  border-bottom: 1px solid #dce5f0;
  cursor: move;
  touch-action: none;
  user-select: none;
}

.ai-header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ai-header-icon {
  font-size: 22px;
}

.ai-header-name {
  font-size: 15px;
  font-weight: 700;
}

.ai-header-sub {
  font-size: 11px;
  color: #66758a;
  letter-spacing: 0;
}

.ai-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.ai-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.ai-icon-btn:hover {
  color: #12325a;
  background: #eaf3ff;
}

.ai-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ai-icon-btn-close:hover {
  color: #b3361d;
  background: #fdeeea;
}

/* 图钉激活态: 颜色加深 + 浅色底色, 与悬停态区分 */
.ai-pin-btn-active {
  color: #1a5fa8;
  background: rgba(26, 95, 168, 0.12);
}

.ai-pin-btn-active:hover {
  color: #12325a;
  background: rgba(26, 95, 168, 0.2);
}

/* ===== 会话切换面板 ===== */
.ai-session-menu {
  border-bottom: 1px solid #e6edf6;
  padding: 8px 12px 10px;
  background: #f7faff;
  max-height: 220px;
  overflow: auto;
}

.ai-session-menu-title {
  font-size: 12px;
  color: #66758a;
  margin-bottom: 6px;
}

.ai-session-menu-empty {
  font-size: 12px;
  color: #94a2b8;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
}

.ai-session-menu-item {
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.ai-session-menu-item:hover {
  background: #e6edf6;
}

.ai-session-menu-active {
  background: #d6e5fa;
}

.ai-session-menu-row {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  min-width: 0;
}

.ai-session-menu-name {
  font-size: 13px;
  color: #12325a;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.ai-session-menu-time {
  font-size: 11px;
  color: #94a2b8;
}

/* ===== 错误条 ===== */
.ai-error {
  background: #fdeeea;
  color: #b3361d;
  padding: 8px 12px;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* ===== 消息区 ===== */
.ai-drawer-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ai-empty {
  margin: auto;
  text-align: center;
  color: #66758a;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.ai-empty-icon {
  font-size: 38px;
  color: #1a5fa8;
}

.ai-empty-title {
  font-size: 15px;
  font-weight: 700;
  color: #12325a;
}

.ai-empty-sub {
  font-size: 12px;
  max-width: 300px;
  line-height: 1.6;
}

.ai-msg {
  display: flex;
  width: 100%;
}

.ai-msg-user {
  justify-content: flex-end;
}

.ai-msg-assistant {
  justify-content: flex-start;
}

.ai-msg-tool {
  justify-content: flex-start;
}

.ai-msg-bubble {
  max-width: min(720px, 82%);
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.ai-msg-user .ai-msg-bubble {
  background: #1a5fa8;
  color: #ffffff;
  border-bottom-right-radius: 4px;
}

.ai-msg-assistant .ai-msg-bubble {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  background: #ffffff;
  color: #172033;
  border: 1px solid #dce5f0;
  border-bottom-left-radius: 4px;
}

.ai-md-body :deep(p) {
  margin: 0 0 6px;
}

.ai-md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.ai-md-body :deep(pre) {
  background: #f4f7fb;
  border: 1px solid #dce5f0;
  border-radius: 6px;
  padding: 8px;
  overflow: auto;
  font-size: 12px;
}

.ai-md-body :deep(code) {
  background: #f4f7fb;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}

.ai-md-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 6px 0;
}

.ai-md-body :deep(th),
.ai-md-body :deep(td) {
  border: 1px solid #dce5f0;
  padding: 4px 6px;
  font-size: 12px;
}

.ai-cursor {
  display: inline-block;
  margin-left: 2px;
  color: #1a5fa8;
  animation: ai-blink 1s steps(1) infinite;
}

@keyframes ai-blink {
  50% {
    opacity: 0;
  }
}

/* ===== 工具卡片 ===== */
.ai-tool-card {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  font-size: 12px;
}

.ai-tool-card-pending {
  border-color: #f0a040;
  background: #fff8eb;
}

.ai-tool-card-rejected {
  border-color: #d6422b;
  background: #fdeeea;
}

.ai-tool-card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #12325a;
}

.ai-tool-card-name {
  font-weight: 600;
}

.ai-tool-card-status {
  color: #66758a;
}

.ai-tool-card-status-ok {
  color: #168a4f;
}

.ai-tool-card-section {
  margin-top: 4px;
}

.ai-tool-card-section-title {
  color: #66758a;
  font-size: 11px;
  margin-bottom: 2px;
}

.ai-tool-card-pre {
  background: #f4f7fb;
  border: 1px solid #dce5f0;
  border-radius: 4px;
  padding: 6px;
  margin: 0;
  max-height: 200px;
  overflow: auto;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 待确认卡片 (置顶醒目) ===== */
.ai-pending-card {
  background: #fff8eb;
  border: 2px solid #f0a040;
  border-radius: 8px;
  padding: 10px 12px;
}

.ai-pending-title {
  color: #b56b00;
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 6px;
}

.ai-pending-meta {
  font-size: 12px;
  color: #34445d;
  margin-bottom: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ai-pending-section {
  margin-bottom: 8px;
}

.ai-pending-actions {
  display: flex;
  gap: 8px;
}

/* ===== 输入区 ===== */
.ai-drawer-footer {
  border-top: 1px solid #dce5f0;
  background: #ffffff;
  padding: 10px 12px;
}

.ai-input {
  width: 100%;
  resize: none;
  border: 1px solid #dce5f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.16s ease;
  font-family: inherit;
}

.ai-input:focus {
  border-color: #1a5fa8;
}

.ai-input:disabled {
  background: #f4f7fb;
  color: #94a2b8;
}

.ai-input-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}

.ai-input-tip {
  font-size: 11px;
  color: #66758a;
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-tool-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #66758a;
  cursor: pointer;
  user-select: none;
}

.ai-tool-toggle input {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: #1a5fa8;
  cursor: pointer;
}

.ai-input-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.ai-send-button {
  width: 34px;
  min-width: 34px;
  height: 32px;
  padding: 0;
}

.ai-stop-square {
  display: inline-block;
  width: 11px;
  height: 11px;
  background: currentColor;
  border-radius: 2px;
}

.ai-model-switch {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  background: #eef4fb;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}

.ai-model-option {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 44px;
  height: 28px;
  padding: 0 9px;
  color: #66758a;
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.ai-model-option:hover {
  color: #12325a;
  background: #eaf3ff;
}

.ai-model-option-active {
  color: #12325a;
  background: #ffffff;
  box-shadow: 0 1px 4px rgba(18, 50, 90, 0.14);
}

.ai-model-option:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.ai-resize-handle {
  position: absolute;
  z-index: 2;
  touch-action: none;
}

.ai-resize-handle-n,
.ai-resize-handle-s {
  left: 10px;
  right: 10px;
  height: 8px;
  cursor: ns-resize;
}

.ai-resize-handle-n {
  top: 0;
}

.ai-resize-handle-s {
  bottom: 0;
}

.ai-resize-handle-e,
.ai-resize-handle-w {
  top: 10px;
  bottom: 10px;
  width: 8px;
  cursor: ew-resize;
}

.ai-resize-handle-e {
  right: 0;
}

.ai-resize-handle-w {
  left: 0;
}

.ai-resize-handle-ne,
.ai-resize-handle-nw,
.ai-resize-handle-se,
.ai-resize-handle-sw {
  width: 14px;
  height: 14px;
}

.ai-resize-handle-ne {
  top: 0;
  right: 0;
  cursor: nesw-resize;
}

.ai-resize-handle-nw {
  top: 0;
  left: 0;
  cursor: nwse-resize;
}

.ai-resize-handle-se {
  right: 0;
  bottom: 0;
  cursor: nwse-resize;
}

.ai-resize-handle-sw {
  left: 0;
  bottom: 0;
  cursor: nesw-resize;
}

.ai-side-resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 3;
  width: 10px;
  cursor: ew-resize;
  touch-action: none;
}

.ai-side-resize-handle::after {
  position: absolute;
  top: 50%;
  left: 3px;
  width: 3px;
  height: 48px;
  content: "";
  background: #b9cff0;
  border-radius: 3px;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.16s ease;
}

.ai-side-resize-handle:hover::after {
  opacity: 1;
}

@media (min-width: 768px) {
  .ai-launcher-root {
    position: fixed;
    inset: 0;
    z-index: 2000;
    pointer-events: none;
  }

  .ai-drawer-side {
    position: absolute;
    top: 0;
    right: 0;
    width: 420px;
    height: 100vh;
    border: 0;
    border-left: 1px solid #dce5f0;
    border-radius: 0;
    box-shadow: -4px 0 16px rgba(18, 50, 90, 0.06);
    visibility: visible;
  }

  .ai-drawer-side .ai-drawer-header {
    min-height: 62px;
    padding: 12px 14px;
    cursor: default;
    touch-action: auto;
  }

  .ai-drawer-side .ai-session-menu {
    background: #f8fafc;
  }

  .ai-drawer-side .ai-drawer-footer {
    padding: 14px;
    background: #ffffff;
  }

  .ai-drawer-floating {
    border-radius: 12px;
  }

  .ai-drawer-side .ai-input {
    min-height: 86px;
    border-radius: 12px;
    background: #ffffff;
  }

  .ai-drawer-side .ai-input-bar {
    gap: 10px;
  }

  .ai-drawer-side .ai-input-tip {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ai-drawer-side .ai-msg-user .ai-msg-bubble {
    max-width: 340px;
  }
}

@media (max-width: 767.98px) {
  /* 关键: root 在手机端必须 pointer-events:none, 否则其 fixed inset:0 会拦截 mobile-topbar 的点击,
     使得 mobile-topbar 上的 AI 图标按钮无法再被点击关闭浮窗.
     仅 .ai-drawer (浮窗自身) 与 .ai-fab 子元素恢复 auto 接收事件. */
  .ai-launcher-mobile {
    position: fixed;
    inset: 0;
    z-index: 1800;
    pointer-events: none;
  }

  .ai-launcher-mobile .ai-drawer,
  .ai-launcher-mobile .ai-fab {
    pointer-events: auto;
  }

  /* 手机端入口由 App.vue 的 mobile-topbar AI 图标按钮提供, 隐藏右下角 FAB 避免争夺 viewport */
  .ai-launcher-mobile .ai-fab {
    display: none !important;
  }

  /* 抽屉切换为底部上拉的全屏 sheet, 用 !important 压住组件 :style 注入的 left/top/width/height.
     起始 top 让出 56px mobile-topbar 高度, 使顶栏的汉堡/AI 按钮始终可点 */
  .ai-launcher-mobile .ai-drawer {
    position: fixed !important;
    left: 0 !important;
    top: var(--app-mobile-topbar-h) !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100vw !important;
    height: calc(100dvh - var(--app-mobile-topbar-h)) !important;
    max-width: 100vw !important;
    max-height: calc(100dvh - var(--app-mobile-topbar-h)) !important;
    border-radius: 0 !important;
    border: 0 !important;
    visibility: visible !important;
    z-index: 1850;
  }

  /* 隐藏拖动改尺寸的手柄, 触屏无意义 */
  .ai-launcher-mobile .ai-resize-handle,
  .ai-launcher-mobile .ai-side-resize-handle {
    display: none !important;
  }

  /* 头部不可拖动, 恢复正常 cursor */
  .ai-launcher-mobile .ai-drawer-header {
    cursor: default;
    touch-action: auto;
  }

  /* 模式切换按钮 (侧栏/悬浮窗) 在手机端无意义, 隐藏 */
  .ai-launcher-mobile .ai-drawer-header .ai-icon-btn[aria-label="切换为悬浮小窗"],
  .ai-launcher-mobile .ai-drawer-header .ai-icon-btn[aria-label="切换为右侧栏"] {
    display: none;
  }

  /* 输入区底部安全区 (iPhone home indicator) */
  .ai-launcher-mobile .ai-drawer-footer {
    padding-bottom: calc(10px + env(safe-area-inset-bottom));
  }
}
</style>
