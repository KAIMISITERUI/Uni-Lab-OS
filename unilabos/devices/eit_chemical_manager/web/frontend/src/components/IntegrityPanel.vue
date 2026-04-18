<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type IntegrityReport,
  deduplicate,
  fetchIntegrity,
} from '../api/chemicals'

const report = ref<IntegrityReport | null>(null)
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    report.value = await fetchIntegrity()
  } catch (err: unknown) {
    ElMessage.error((err as Error).message || '获取完整性报告失败')
  } finally {
    loading.value = false
  }
}

async function runDeduplicate() {
  try {
    await ElMessageBox.confirm(
      '将按 CAS 号去重, 保留每组中 id 最小的行, 此操作不可撤销, 是否继续?',
      '确认去重',
      { type: 'warning' },
    )
  } catch {
    return
  }

  try {
    const resp = await deduplicate()
    ElMessage.success(`已去重, 删除 ${resp.deleted} 条`)
    await refresh()
  } catch (err: unknown) {
    ElMessage.error((err as Error).message || '去重失败')
  }
}

onMounted(refresh)
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-weight: 600">完整性报告</span>
        <el-button size="small" @click="refresh">刷新</el-button>
        <el-button size="small" type="warning" @click="runDeduplicate">按 CAS 去重</el-button>
      </div>
    </template>

    <el-descriptions v-if="report" :column="3" border>
      <el-descriptions-item label="总条数">{{ report.total }}</el-descriptions-item>
      <el-descriptions-item label="缺 CAS 行数">{{ report.no_cas }}</el-descriptions-item>
      <el-descriptions-item label="缺名称行数">{{ report.no_name }}</el-descriptions-item>
    </el-descriptions>

    <div v-if="report && report.duplicated_cas.length > 0" style="margin-top: 16px">
      <div style="font-weight: 600; margin-bottom: 8px">CAS 重复:</div>
      <el-table :data="report.duplicated_cas" border>
        <el-table-column prop="cas_number" label="CAS 号" />
        <el-table-column prop="cnt" label="重复次数" width="120" />
      </el-table>
    </div>
    <div v-else-if="report" style="margin-top: 16px; color: #67c23a">
      未发现 CAS 重复
    </div>
  </el-card>
</template>
