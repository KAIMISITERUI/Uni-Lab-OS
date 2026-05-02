<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Document,
  Key,
  Menu,
} from '@element-plus/icons-vue'
import { setApiToken } from './api/chemicals'
import { AiAgentLauncher } from './features/ai-agent'
import { useAiAgent } from './features/ai-agent/state/useAiAgent'
import { useViewportMode } from './composables/useViewportMode'
import AppNavSidebar from './components/AppNavSidebar.vue'

const route = useRoute()
const { isMobile } = useViewportMode()
const ai = useAiAgent()

const title = computed(() => String(route.meta.title || 'EIT Hub'))
const nowText = computed(() => new Date().toLocaleString('zh-CN', { hour12: false }))
const tokenDialog = ref(false)
const tokenInput = ref('')
const agvMenuOpen = ref(false)
const synthesisMenuOpen = ref(false)
// 手机端汉堡抽屉的开合状态, 桌面端不使用此 ref
const mobileNavOpen = ref(false)
const synthesisGroupActive = computed(() => {
  // /synthesis 与其子路由 (如 /synthesis/cameras) 视为合成工站组高亮,
  // 但要排除独立的 /synthesis-task-editor 与 /synthesis-workflow 路由.
  const path = route.path
  return path === '/synthesis' || path.startsWith('/synthesis/') === true
})

onMounted(() => {
  const savedToken = localStorage.getItem('chem_mgr_token') || ''
  if (savedToken.trim() !== '') {
    setApiToken(savedToken)
  }
})

watch(
  () => route.path,
  (path) => {
    agvMenuOpen.value = path.startsWith('/agv') === true
    synthesisMenuOpen.value = path === '/synthesis' || path.startsWith('/synthesis/') === true
    // 路由切换后自动收起手机抽屉, 避免遮挡内容
    mobileNavOpen.value = false
  },
  { immediate: true },
)

function openTokenDialog (): void {
  tokenInput.value = localStorage.getItem('chem_mgr_token') || ''
  tokenDialog.value = true
}

function saveToken (): void {
  const token = tokenInput.value.trim()
  if (token === '') {
    localStorage.removeItem('chem_mgr_token')
    setApiToken('')
    ElMessage.success('已清除访问令牌')
  } else {
    localStorage.setItem('chem_mgr_token', token)
    setApiToken(token)
    ElMessage.success('访问令牌已保存')
  }
  tokenDialog.value = false
}

function openMobileNav (): void {
  mobileNavOpen.value = true
}

function onMobileNavClick (): void {
  // 抽屉内菜单点击, 立即关闭抽屉
  mobileNavOpen.value = false
}

function toggleAiPanel (): void {
  ai.toggle()
}
</script>

<template>
  <div class="app-shell">
    <!-- 桌面端固定侧栏: 手机端通过 styles.css 的 .app-shell > .sidebar 隐藏, 不渲染时同样有效 -->
    <AppNavSidebar
      v-if="isMobile === false"
      v-model:agv-menu-open="agvMenuOpen"
      v-model:synthesis-menu-open="synthesisMenuOpen"
      :synthesis-group-active="synthesisGroupActive"
    />

    <!-- 手机端汉堡抽屉: 内部沿用同一 AppNavSidebar 组件, 视觉与桌面侧栏完全一致 -->
    <el-drawer
      v-if="isMobile === true"
      v-model="mobileNavOpen"
      direction="ltr"
      size="280px"
      :with-header="false"
      modal-class="mobile-nav-drawer-modal"
      class="mobile-nav-drawer"
    >
      <AppNavSidebar
        v-model:agv-menu-open="agvMenuOpen"
        v-model:synthesis-menu-open="synthesisMenuOpen"
        :synthesis-group-active="synthesisGroupActive"
        @nav-click="onMobileNavClick"
      />
    </el-drawer>

    <section class="workspace">
      <!-- 桌面端 topbar (手机端通过 .workspace > .topbar { display: none } 隐藏) -->
      <header class="topbar">
        <h2 class="topbar-title">{{ title }}</h2>
        <div class="topbar-meta">
          <el-icon><Document /></el-icon>
          <span>{{ nowText }}</span>
          <el-button text @click="openTokenDialog">访问令牌</el-button>
        </div>
      </header>

      <!-- 手机端 mobile-topbar: 固定在 .workspace 顶部, 通过 styles.css 在桌面隐藏 -->
      <header class="mobile-topbar">
        <button
          type="button"
          class="mobile-topbar-btn mobile-topbar-btn-menu"
          aria-label="打开导航"
          @click="openMobileNav"
        >
          <el-icon><Menu /></el-icon>
        </button>
        <h2 class="mobile-topbar-title">{{ title }}</h2>
        <div class="mobile-topbar-actions">
          <button
            type="button"
            class="mobile-topbar-btn"
            aria-label="访问令牌"
            @click="openTokenDialog"
          >
            <el-icon><Key /></el-icon>
          </button>
          <button
            type="button"
            class="mobile-topbar-btn"
            :class="{ 'mobile-topbar-btn-active': ai.state.open === true }"
            aria-label="AI 助手"
            @click="toggleAiPanel"
          >
            <el-icon><ChatDotRound /></el-icon>
          </button>
        </div>
      </header>

      <main class="content-scroll">
        <RouterView v-slot="{ Component }">
          <KeepAlive>
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </section>

    <el-dialog v-model="tokenDialog" title="访问令牌" width="420px">
      <el-form label-width="110px">
        <el-form-item label="X-API-Token">
          <el-input
            v-model="tokenInput"
            placeholder="后端未设置 CHEM_MGR_WEB_TOKEN 时可留空"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tokenDialog = false">取消</el-button>
        <el-button type="primary" @click="saveToken">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 助手浮动入口, 挂在 .app-shell 末尾以脱离 KeepAlive RouterView, 跨路由保持状态 -->
    <AiAgentLauncher />
  </div>
</template>

<style scoped>
/* mobile-topbar 仅在手机端可见, 桌面通过下方 @media 隐藏 */
.mobile-topbar {
  display: none;
}

@media (max-width: 767.98px) {
  .topbar {
    display: none;
  }

  .mobile-topbar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    /* 顶栏只覆盖普通页面内容, 弹窗和抽屉由全局层级规则管理. */
    z-index: 1900;
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--app-mobile-topbar-h);
    padding: 0 12px;
    background: #ffffff;
    border-bottom: 1px solid #dce5f0;
    box-shadow: 0 2px 8px rgba(18, 50, 90, 0.06);
  }

  .mobile-topbar-title {
    flex: 1 1 auto;
    margin: 0;
    color: #12325a;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-topbar-actions {
    display: flex;
    flex: 0 0 auto;
    gap: 4px;
  }

  .mobile-topbar-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    padding: 0;
    color: #12325a;
    background: transparent;
    border: 0;
    border-radius: 8px;
    cursor: pointer;
    font-size: 22px;
  }

  .mobile-topbar-btn:hover {
    background: #eaf3ff;
  }

  .mobile-topbar-btn:active {
    background: #d6e5fa;
  }

  .mobile-topbar-btn-menu {
    flex: 0 0 auto;
  }

  .mobile-topbar-btn-active {
    color: #1a5fa8;
    background: rgba(26, 95, 168, 0.12);
  }

  .mobile-topbar-btn .el-icon {
    font-size: 22px;
  }
}
</style>
