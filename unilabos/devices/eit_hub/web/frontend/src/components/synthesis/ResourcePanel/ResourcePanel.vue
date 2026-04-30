<template>
  <!--
    功能:
      合成页右侧资源管理面板. 渲染 录入资源 / 移动资源 / 编辑资源 / 移出资源 入口按钮.
      按钮区提供 刷新资源 按钮, 触发父组件注入的 onRefresh 回调以同步主 3D 视图.
    事件:
      success: 资源变更成功后通知父组件刷新主 3D 视图与库存
    Props:
      onRefresh: 父组件注入的异步刷新回调, 用于点击刷新按钮时强制同步主 3D 视图
  -->
  <div class="resource-panel">
    <div class="panel-header">
      <span class="title">资源管理</span>
    </div>
    <div class="panel-body">
      <el-button
        class="resource-action-button"
        :icon="iconRefresh"
        :loading="refreshing"
        @click="handleRefresh"
      >
        刷新资源
      </el-button>
      <el-button class="resource-action-button" :icon="iconPlus" @click="openDialog()">录入资源</el-button>
      <el-button class="resource-action-button" :icon="iconMove" @click="openMoveDialog()">移动资源</el-button>
      <el-button class="resource-action-button" :icon="iconEdit" @click="openEditDialog()">编辑资源</el-button>
      <el-button class="resource-action-button" :icon="iconDelete" @click="openRemoveDialog()">移出资源</el-button>
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
import { ElMessage } from 'element-plus'
import { Delete, Edit, Plus, Rank, Refresh } from '@element-plus/icons-vue'
import ResourceAddDialog from './ResourceAddDialog.vue'
import ResourceEditDialog from './ResourceEditDialog.vue'
import ResourceMoveDialog from './ResourceMoveDialog.vue'
import ResourceRemoveDialog from './ResourceRemoveDialog.vue'

const props = defineProps<{
  // 父组件注入的异步刷新回调, 点击刷新按钮时调用以同步主 3D 视图
  onRefresh?: () => Promise<void>
}>()

const emit = defineEmits<{
  (e: 'success'): void
}>()

const iconPlus = Plus
const iconEdit = Edit
const iconMove = Rank
const iconDelete = Delete
const iconRefresh = Refresh
const dialogVisible = ref(false)
const removeDialogVisible = ref(false)
const editDialogVisible = ref(false)
const moveDialogVisible = ref(false)
const initialLayoutCode = ref('')
const editLayoutCode = ref('')
const moveLayoutCode = ref('')
const refreshing = ref(false)

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

// 手动刷新主 3D 视图. 复用父组件注入的 onRefresh 回调, refreshing 标志防止并发重复触发
async function handleRefresh (): Promise<void> {
  if (refreshing.value === true) {
    return
  }
  if (typeof props.onRefresh !== 'function') {
    return
  }
  refreshing.value = true
  try {
    await props.onRefresh()
    ElMessage.success('已刷新 3D 视图')
  } catch (err) {
    console.error('[ResourcePanel] 刷新失败:', err)
    ElMessage.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

defineExpose({ openDialog, openRemoveDialog, openEditDialog, openMoveDialog })
</script>

<style scoped>
.resource-panel {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
}
.panel-header {
  padding: 10px;
  border-bottom: 1px solid #ebeef5;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.panel-header .title {
  overflow: hidden;
  min-width: 0;
  font-weight: 600;
  color: #303133;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-body {
  padding: 10px;
  display: grid;
  gap: 10px;
}
.resource-action-button {
  justify-content: center;
  width: 100%;
  height: 42px;
  min-height: 42px;
  margin-left: 0;
  padding: 0 8px;
  color: #12325a;
  font-weight: 600;
  background: #f5f8fc;
  border-color: #d6e1ee;
}
.resource-action-button:hover,
.resource-action-button:focus {
  color: #0f4f86;
  background: #edf4fb;
  border-color: #b9cbe0;
}
.resource-action-button:active {
  color: #0f4f86;
  background: #e5eef8;
  border-color: #a8bdd4;
}
</style>
