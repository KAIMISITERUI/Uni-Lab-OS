<template>
  <!--
    功能:
      合成页右侧资源管理面板. 渲染 录入资源 / 移动资源 / 编辑资源 / 删除资源 入口按钮.
    事件:
      success: 资源变更成功后通知父组件刷新主 3D 视图与库存
  -->
  <div class="resource-panel">
    <div class="panel-header">
      <span class="title">资源管理</span>
    </div>
    <div class="panel-body">
      <el-button type="primary" :icon="iconPlus" @click="openDialog()">录入资源</el-button>
      <el-button type="success" :icon="iconMove" @click="openMoveDialog()">移动资源</el-button>
      <el-button type="warning" :icon="iconEdit" @click="openEditDialog()">编辑资源</el-button>
      <el-button type="danger" :icon="iconDelete" @click="openRemoveDialog()">删除资源</el-button>
    </div>
    <ResourceAddDialog
      v-model:visible="dialogVisible"
      :initial-layout-code="initialLayoutCode"
      @success="onSuccess"
    />
    <ResourceEditDialog
      v-model:visible="editDialogVisible"
      :initial-layout-code="editLayoutCode"
      @success="onSuccess"
    />
    <ResourceMoveDialog
      v-model:visible="moveDialogVisible"
      :initial-layout-code="moveLayoutCode"
      @success="onSuccess"
    />
    <ResourceRemoveDialog
      v-model:visible="removeDialogVisible"
      @success="onSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Delete, Edit, Plus, Rank } from '@element-plus/icons-vue'
import ResourceAddDialog from './ResourceAddDialog.vue'
import ResourceEditDialog from './ResourceEditDialog.vue'
import ResourceMoveDialog from './ResourceMoveDialog.vue'
import ResourceRemoveDialog from './ResourceRemoveDialog.vue'

const emit = defineEmits<{
  (e: 'success'): void
}>()

const iconPlus = Plus
const iconEdit = Edit
const iconMove = Rank
const iconDelete = Delete
const dialogVisible = ref(false)
const removeDialogVisible = ref(false)
const editDialogVisible = ref(false)
const moveDialogVisible = ref(false)
const initialLayoutCode = ref('')
const editLayoutCode = ref('')
const moveLayoutCode = ref('')

// 暴露方法供父组件 (例如右键菜单触发) 携带 layout_code 打开对话框
function openDialog (layoutCode?: string): void {
  initialLayoutCode.value = layoutCode || ''
  dialogVisible.value = true
}

function openRemoveDialog (): void {
  removeDialogVisible.value = true
}

function openEditDialog (layoutCode?: string): void {
  // 编辑入口直接打开对话框, 由对话框内部的 位置码 输入 / 3D 点击 选目标托盘
  editLayoutCode.value = (layoutCode || '').trim()
  editDialogVisible.value = true
}

function openMoveDialog (layoutCode?: string): void {
  // 移动入口可携带源位置码, 对话框内部继续选择目标槽位
  moveLayoutCode.value = (layoutCode || '').trim()
  moveDialogVisible.value = true
}

function onSuccess (): void {
  emit('success')
}

defineExpose({ openDialog, openRemoveDialog, openEditDialog, openMoveDialog })
</script>

<style scoped>
.resource-panel {
  width: 100%;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
}
.panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: linear-gradient(180deg, #f6f9ff 0%, #eef3fb 100%);
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
}
.panel-header .title {
  font-weight: 600;
  color: #303133;
}
.panel-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
