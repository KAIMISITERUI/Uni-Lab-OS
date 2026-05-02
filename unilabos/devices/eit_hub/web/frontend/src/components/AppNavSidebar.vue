<script setup lang="ts">
/**
 * 功能:
 *   全局导航侧栏组件. 抽离自 App.vue, 用于桌面端固定侧栏与手机端抽屉两处共用,
 *   同一份模板与样式, 仅父容器位置不同.
 *   合成/AGV 子菜单展开状态由父组件以 v-model 提供, 避免组件自持状态导致两实例不同步.
 *
 * 参数:
 *   agvMenuOpen:        boolean        AGV 子菜单展开标志, 与 v-model:agv-menu-open 配合
 *   synthesisMenuOpen:  boolean        合成工站子菜单展开标志, 与 v-model:synthesis-menu-open 配合
 *   synthesisGroupActive: boolean      合成工站组高亮 (含 /synthesis 与 /synthesis/cameras)
 *
 * 返回:
 *   无 (Vue 组件)
 */
import { computed } from 'vue'
import {
  ArrowDown,
  ChatDotRound,
  Connection,
  Document,
  EditPen,
  Files,
  MapLocation,
  Operation,
  Printer,
  TakeawayBox,
  Tools,
  VideoCamera,
} from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

interface Props {
  agvMenuOpen: boolean
  synthesisMenuOpen: boolean
  synthesisGroupActive: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:agvMenuOpen', value: boolean): void
  (e: 'update:synthesisMenuOpen', value: boolean): void
  (e: 'nav-click'): void
}>()

const route = useRoute()
const agvMenuExpanded = computed(() => props.agvMenuOpen === true)
const synthesisMenuExpanded = computed(() => props.synthesisMenuOpen === true)

function toggleAgvMenu (): void {
  emit('update:agvMenuOpen', props.agvMenuOpen === false)
}

function toggleSynthesisMenu (): void {
  emit('update:synthesisMenuOpen', props.synthesisMenuOpen === false)
}

function emitNavClick (): void {
  // 父组件用此事件在手机端关闭抽屉; 桌面端可忽略
  emit('nav-click')
}

// 设置一级菜单点击时同步父组件菜单展开状态
function onSynthesisGroupClick (): void {
  emit('update:synthesisMenuOpen', true)
  emitNavClick()
}

function onAgvGroupClick (): void {
  emit('update:agvMenuOpen', true)
  emitNavClick()
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand-block">
      <h1 class="brand-title">EIT Hub</h1>
      <p class="brand-subtitle">Uni-Lab OS Workstations</p>
    </div>

    <nav class="nav-list">
      <RouterLink class="nav-link" to="/devices" @click="emitNavClick">
        <el-icon><Connection /></el-icon>
        <span>设备总览</span>
      </RouterLink>

      <div class="nav-group-control" :class="{ 'nav-group-active': synthesisGroupActive }">
        <RouterLink
          class="nav-link nav-link-group-main"
          to="/synthesis"
          @click="onSynthesisGroupClick"
        >
          <svg
            class="nav-station-icon"
            viewBox="224 176 576 704"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            stroke="currentColor"
            stroke-width="44"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M408 240h208" />
            <path d="M440 240v160" />
            <path d="M584 240v160" />
            <path
              d="M440 400L272 704
                 a72 72 0 0 0 64 108
                 h352
                 a72 72 0 0 0 64-108
                 L584 400"
            />
            <line x1="360" y1="600" x2="664" y2="600" />
          </svg>
          <span>合成工站</span>
        </RouterLink>
        <button
          class="nav-arrow-button"
          type="button"
          :aria-expanded="synthesisMenuExpanded"
          aria-label="展开合成工站子菜单"
          @click="toggleSynthesisMenu"
        >
          <el-icon class="nav-arrow" :class="{ 'nav-arrow-open': synthesisMenuExpanded }"><ArrowDown /></el-icon>
        </button>
      </div>
      <div v-if="synthesisMenuExpanded" class="nav-sub-list">
        <RouterLink class="nav-link nav-sub" to="/synthesis/cameras" @click="emitNavClick">
          <el-icon><VideoCamera /></el-icon>
          <span>现场监控</span>
        </RouterLink>
      </div>

      <RouterLink class="nav-link" to="/analysis" @click="emitNavClick">
        <svg
          class="nav-station-icon"
          viewBox="96 224 928 608"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          stroke="currentColor"
          stroke-width="64"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path
            d="M160 680
               H304
               C368 680 372 520 396 420
               C420 320 456 248 512 248
               C568 248 604 320 628 420
               C652 520 656 680 720 680
               H984"
          />
        </svg>
        <span>分析工站</span>
      </RouterLink>

      <div class="nav-group-control" :class="{ 'nav-group-active': route.path.startsWith('/agv') === true }">
        <RouterLink class="nav-link nav-link-group-main" to="/agv" @click="onAgvGroupClick">
          <svg
            class="nav-station-icon"
            viewBox="1 5 22 17"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <rect x="3.5" y="8" width="17" height="8" rx="1.6" />
            <path d="M6.2 16a2.3 2.3 0 0 0 4.6 0" />
            <path d="M13.2 16a2.3 2.3 0 0 0 4.6 0" />
          </svg>
          <span>AGV 运输车</span>
        </RouterLink>
        <button
          class="nav-arrow-button"
          type="button"
          :aria-expanded="agvMenuExpanded"
          aria-label="展开 AGV 子菜单"
          @click="toggleAgvMenu"
        >
          <el-icon class="nav-arrow" :class="{ 'nav-arrow-open': agvMenuExpanded }"><ArrowDown /></el-icon>
        </button>
      </div>
      <div v-if="agvMenuExpanded" class="nav-sub-list">
        <RouterLink class="nav-link nav-sub" to="/agv/positions" @click="emitNavClick">
          <el-icon><MapLocation /></el-icon>
          <span>点位管理</span>
        </RouterLink>
        <RouterLink class="nav-link nav-sub" to="/agv/shelf" @click="emitNavClick">
          <el-icon><TakeawayBox /></el-icon>
          <span>货架状态</span>
        </RouterLink>
      </div>

      <RouterLink class="nav-link" to="/chemicals" @click="emitNavClick">
        <el-icon><Files /></el-icon>
        <span>化学品库</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/synthesis-task-editor" @click="emitNavClick">
        <el-icon><EditPen /></el-icon>
        <span>任务编辑</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/synthesis-workflow" @click="emitNavClick">
        <el-icon><Operation /></el-icon>
        <span>工作流</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/task-history" @click="emitNavClick">
        <el-icon><Document /></el-icon>
        <span>任务历史</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/maintenance" @click="emitNavClick">
        <el-icon><Tools /></el-icon>
        <span>运维管理</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/ai-agent-history" @click="emitNavClick">
        <el-icon><ChatDotRound /></el-icon>
        <span>AI 助手</span>
      </RouterLink>
      <RouterLink class="nav-link" to="/label-printer" @click="emitNavClick">
        <el-icon><Printer /></el-icon>
        <span>标签打印机</span>
      </RouterLink>
    </nav>
  </aside>
</template>
