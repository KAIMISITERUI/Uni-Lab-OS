<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { setApiToken } from './api/chemicals'

const tokenDialog = ref(false)
const tokenInput = ref('')

onMounted(() => {
  // 已存 token 不再提示
  if (!localStorage.getItem('chem_mgr_token')) {
    tokenDialog.value = false
  }
})

function openTokenDialog() {
  tokenInput.value = localStorage.getItem('chem_mgr_token') || ''
  tokenDialog.value = true
}

function saveToken() {
  const v = tokenInput.value.trim()
  if (v === '') {
    localStorage.removeItem('chem_mgr_token')
    setApiToken('')
    ElMessage.success('已清除访问令牌')
  } else {
    localStorage.setItem('chem_mgr_token', v)
    setApiToken(v)
    ElMessage.success('访问令牌已保存')
  }
  tokenDialog.value = false
}
</script>

<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">化学品库管理</div>
      <el-menu
        class="nav"
        mode="horizontal"
        :ellipsis="false"
        :default-active="$route.path"
        router
      >
        <el-menu-item index="/chemicals">化学品列表</el-menu-item>
        <el-menu-item index="/integrity">完整性维护</el-menu-item>
      </el-menu>
      <el-button text @click="openTokenDialog">访问令牌</el-button>
    </el-header>

    <el-main>
      <router-view />
    </el-main>

    <el-dialog v-model="tokenDialog" title="访问令牌" width="420px">
      <el-form>
        <el-form-item label="X-API-Token">
          <el-input
            v-model="tokenInput"
            placeholder="后端未设置 CHEM_MGR_WEB_TOKEN 时可留空"
            show-password
          />
        </el-form-item>
        <el-form-item>
          <small>用于鉴权请求头, 仅保存在本机 localStorage 中</small>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tokenDialog = false">取消</el-button>
        <el-button type="primary" @click="saveToken">保存</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style>
html, body, #app {
  height: 100%;
  margin: 0;
}

.layout {
  height: 100%;
}

.header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.brand {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.nav {
  flex: 1;
  border-bottom: none !important;
}
</style>
