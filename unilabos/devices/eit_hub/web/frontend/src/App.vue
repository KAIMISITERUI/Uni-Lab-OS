<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Cpu,
  Document,
  EditPen,
  Files,
  Monitor,
  Printer,
  Van,
} from '@element-plus/icons-vue'
import { setApiToken } from './api/chemicals'

const route = useRoute()

const title = computed(() => String(route.meta.title || 'EIT Hub'))
const nowText = computed(() => new Date().toLocaleString('zh-CN', { hour12: false }))
const tokenDialog = ref(false)
const tokenInput = ref('')

onMounted(() => {
  const savedToken = localStorage.getItem('chem_mgr_token') || ''
  if (savedToken.trim() !== '') {
    setApiToken(savedToken)
  }
})

function openTokenDialog() {
  tokenInput.value = localStorage.getItem('chem_mgr_token') || ''
  tokenDialog.value = true
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
        <RouterLink class="nav-link" to="/synthesis">
          <el-icon><Cpu /></el-icon>
          <span>合成工站</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/chemicals">
          <el-icon><Files /></el-icon>
          <span>化学品库</span>
        </RouterLink>
        <RouterLink class="nav-link nav-sub" to="/chemical-integrity">
          <el-icon><Document /></el-icon>
          <span>完整性维护</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/analysis">
          <el-icon><Monitor /></el-icon>
          <span>分析工站</span>
        </RouterLink>
        <RouterLink class="nav-link" to="/agv">
          <el-icon><Van /></el-icon>
          <span>AGV 工站</span>
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
        <RouterView />
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
