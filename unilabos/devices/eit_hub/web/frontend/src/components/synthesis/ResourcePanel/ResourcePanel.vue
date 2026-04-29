<template>
  <!--
    功能:
      合成页右侧资源管理面板. 当前仅渲染 录入资源 入口按钮, 其它操作 (删除/编辑/移动/清空/刷新/资源详情) 暂不实现.
    事件:
      success: 录入成功后通知父组件刷新主 3D 视图
  -->
  <div class="resource-panel">
    <div class="panel-header">
      <span class="title">资源管理</span>
    </div>
    <div class="panel-body">
      <el-button type="primary" :icon="iconPlus" @click="openDialog()">录入资源</el-button>
    </div>
    <ResourceAddDialog
      v-model:visible="dialogVisible"
      :initial-layout-code="initialLayoutCode"
      @success="onSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import ResourceAddDialog from './ResourceAddDialog.vue'

const emit = defineEmits<{
  (e: 'success'): void
}>()

const iconPlus = Plus
const dialogVisible = ref(false)
const initialLayoutCode = ref('')

// 暴露方法供父组件 (例如右键菜单触发) 携带 layout_code 打开对话框
function openDialog (layoutCode?: string): void {
  initialLayoutCode.value = layoutCode || ''
  dialogVisible.value = true
}

function onSuccess (): void {
  emit('success')
}

defineExpose({ openDialog })
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
