<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  Connection,
  Document,
  EditPen,
  Files,
  Printer,
} from '@element-plus/icons-vue'
import { setApiToken } from './api/chemicals'

const route = useRoute()

const title = computed(() => String(route.meta.title || 'EIT Hub'))
const nowText = computed(() => new Date().toLocaleString('zh-CN', { hour12: false }))
const tokenDialog = ref(false)
const tokenInput = ref('')
const agvMenuOpen = ref(false)
const agvMenuExpanded = computed(() => agvMenuOpen.value === true)

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
  },
  { immediate: true },
)

function openTokenDialog() {
  tokenInput.value = localStorage.getItem('chem_mgr_token') || ''
  tokenDialog.value = true
}

function toggleAgvMenu() {
  agvMenuOpen.value = agvMenuOpen.value === false
}

function saveToken() {
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
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <h1 class="brand-title">EIT Hub</h1>
        <p class="brand-subtitle">Uni-Lab OS Workstations</p>
      </div>

      <nav class="nav-list">
        <RouterLink class="nav-link" to="/devices">
          <el-icon><Connection /></el-icon>
          <span>设备总览</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/synthesis">
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
        <RouterLink class="nav-link" to="/analysis">
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
          <RouterLink class="nav-link nav-link-group-main" to="/agv" @click="agvMenuOpen = true">
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
          <RouterLink class="nav-link nav-sub" to="/agv/calibration">
            <span>点位校准</span>
          </RouterLink>
          <RouterLink class="nav-link nav-sub" to="/agv/shelf">
            <span>货架状态</span>
          </RouterLink>
        </div>
        <RouterLink class="nav-link" to="/chemicals">
          <el-icon><Files /></el-icon>
          <span>化学品库</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/synthesis-task-editor">
          <el-icon><EditPen /></el-icon>
          <span>任务编辑</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/label-printer">
          <el-icon><Printer /></el-icon>
          <span>标签打印机</span>
        </RouterLink>
      </nav>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <h2 class="topbar-title">{{ title }}</h2>
        <div class="topbar-meta">
          <el-icon><Document /></el-icon>
          <span>{{ nowText }}</span>
          <el-button text @click="openTokenDialog">访问令牌</el-button>
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
  </div>
</template>
