<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchExperimentPlan, type ExperimentPlanResponse, type ParamRowEntry } from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'
import EditableSpreadsheet from '../EditableSpreadsheet.vue'

const props = defineProps<{ taskId: number }>()

const data = ref<ExperimentPlanResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')

const sectionGroups = computed<Array<{ title: string; items: ParamRowEntry[] }>>(() => {
  if (data.value === null) {
    return []
  }
  const groups: Array<{ title: string; items: ParamRowEntry[] }> = []
  let currentTitle = '其他'
  let currentItems: ParamRowEntry[] = []
  for (const entry of data.value.param_rows) {
    if (entry.type === 'section') {
      if (currentItems.length > 0) {
        groups.push({ title: currentTitle, items: currentItems })
      }
      currentTitle = entry.name
      currentItems = []
    } else {
      currentItems.push(entry)
    }
  }
  if (currentItems.length > 0) {
    groups.push({ title: currentTitle, items: currentItems })
  }
  return groups
})

const headers = computed<string[]>(() => data.value?.headers ?? [])
const rowsForTable = computed<unknown[][]>(() => (data.value?.rows ?? []) as unknown[][])

const spreadsheetColumns = computed(() => {
  return headers.value.map((_header, index) => ({
    data: index,
    readOnly: true,
    width: index === 0 ? 90 : 130,
  }))
})

async function load(taskId: number): Promise<void> {
  if (taskId <= 0) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    data.value = await fetchExperimentPlan(taskId)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
    data.value = null
    if (errorMessage.value.includes('未找到') === false) {
      ElMessage.error(errorMessage.value)
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => props.taskId,
  (taskId) => { void load(taskId) },
  { immediate: true },
)

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}
</script>

<template>
  <div v-loading="loading" class="experiment-plan-tab">
    <el-empty v-if="errorMessage !== '' && data === null" :description="errorMessage" />
    <template v-else-if="data !== null">
      <section class="param-area">
        <div v-for="group in sectionGroups" :key="group.title" class="param-group">
          <h4 class="param-title">{{ group.title }}</h4>
          <el-descriptions :column="2" border size="small" class="param-desc">
            <el-descriptions-item
              v-for="item in group.items"
              :key="item.row + ':' + item.name"
              :label="item.name"
            >
              {{ formatValue(item.value) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </section>
      <section class="experiment-area">
        <h4 class="param-title">实验编号 × 反应物</h4>
        <EditableSpreadsheet
          v-if="headers.length > 0"
          :model-value="rowsForTable"
          :col-headers="headers"
          :columns="spreadsheetColumns"
          :height="400"
          stretch-h="all"
        />
        <el-empty v-else description="实验计划未配置反应物列" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.experiment-plan-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
}

.param-area {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 12px;
}

.param-group {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 12px;
}

.param-title {
  margin: 0 0 8px 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.param-desc :deep(.el-descriptions__label) {
  width: 140px;
}

.experiment-area {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
}
</style>
