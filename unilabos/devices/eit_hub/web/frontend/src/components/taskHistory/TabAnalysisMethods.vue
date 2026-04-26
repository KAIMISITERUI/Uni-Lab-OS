<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Document, Warning } from '@element-plus/icons-vue'
import {
  downloadFileUrl,
  fetchFilePreview,
  type CsvPreview,
  type FilePreview,
} from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'

const props = defineProps<{
  taskId: number
  fileStatus: Record<string, { exists: boolean; filename: string }>
}>()

interface MethodPanel {
  key: 'gc_ms' | 'uplc_qtof' | 'hplc'
  label: string
  data: CsvPreview | null
  loading: boolean
  errorMessage: string
}

const panels = ref<MethodPanel[]>([
  { key: 'gc_ms', label: 'GC-MS', data: null, loading: false, errorMessage: '' },
  { key: 'uplc_qtof', label: 'UPLC-QTOF', data: null, loading: false, errorMessage: '' },
  { key: 'hplc', label: 'HPLC', data: null, loading: false, errorMessage: '' },
])

async function loadPanel(panel: MethodPanel): Promise<void> {
  const status = props.fileStatus[panel.key]
  if (status === undefined || status.exists === false) {
    panel.data = null
    panel.errorMessage = ''
    return
  }
  panel.loading = true
  panel.errorMessage = ''
  try {
    const preview = await fetchFilePreview(props.taskId, panel.key)
    panel.data = isCsv(preview) ? preview : null
  } catch (error) {
    panel.errorMessage = getErrorMessage(error)
    panel.data = null
  } finally {
    panel.loading = false
  }
}

function isCsv(preview: FilePreview): preview is CsvPreview {
  return preview.kind === 'csv'
}

async function loadAll(): Promise<void> {
  for (const panel of panels.value) {
    await loadPanel(panel)
  }
}

watch(
  () => props.taskId,
  () => {
    void loadAll()
  },
  { immediate: true },
)

watch(
  () => props.fileStatus,
  () => {
    void loadAll()
  },
  { deep: true },
)

function csvColumns(preview: CsvPreview) {
  return preview.headers.map((header, index) => ({
    prop: `col_${index}`,
    label: header === '' ? `列${index + 1}` : header,
  }))
}

function csvRows(preview: CsvPreview): Record<string, string>[] {
  return preview.rows.map((row) => {
    const record: Record<string, string> = {}
    preview.headers.forEach((_header, index) => {
      record[`col_${index}`] = String(row[index] ?? '')
    })
    return record
  })
}
</script>

<template>
  <div class="analysis-methods-tab">
    <article
      v-for="panel in panels"
      :key="panel.key"
      class="method-panel"
    >
      <header>
        <h4>{{ panel.label }}</h4>
        <div class="actions">
          <span v-if="!fileStatus[panel.key]?.exists" class="missing-tag">
            <el-icon><Warning /></el-icon>
            未启用
          </span>
          <el-button
            v-else
            size="small"
            :icon="Document"
            tag="a"
            :href="downloadFileUrl(taskId, panel.key)"
            download
          >
            下载 CSV
          </el-button>
        </div>
      </header>
      <div v-loading="panel.loading" class="method-body">
        <template v-if="!fileStatus[panel.key]?.exists">
          <el-empty description="此分析方法未启用 (无对应 CSV 文件)" :image-size="80" />
        </template>
        <template v-else-if="panel.errorMessage !== ''">
          <el-alert type="error" :title="panel.errorMessage" show-icon :closable="false" />
        </template>
        <template v-else-if="panel.data !== null">
          <p class="method-meta">{{ fileStatus[panel.key].filename }} · {{ panel.data.rows.length }} 个样品配置</p>
          <el-table
            :data="csvRows(panel.data)"
            border
            stripe
            size="small"
            max-height="320"
          >
            <el-table-column
              v-for="col in csvColumns(panel.data)"
              :key="col.prop"
              :prop="col.prop"
              :label="col.label"
              show-overflow-tooltip
              min-width="120"
            />
          </el-table>
        </template>
      </div>
    </article>
  </div>
</template>

<style scoped>
.analysis-methods-tab {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.method-panel {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}

.method-panel header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.method-panel h4 {
  margin: 0;
  font-size: 14px;
  color: var(--el-color-primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.missing-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.method-body {
  min-height: 80px;
}

.method-meta {
  margin: 0 0 8px 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
