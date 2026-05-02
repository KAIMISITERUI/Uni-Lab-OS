<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchExperimentPlan, type ExperimentPlanResponse, type ParamRowEntry } from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'
import EditableSpreadsheet from '../EditableSpreadsheet.vue'
import { useViewportMode } from '../../composables/useViewportMode'

const props = defineProps<{ taskId: number }>()

const data = ref<ExperimentPlanResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const { isMobile } = useViewportMode()

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

// 三列固定布局: 按 section 名称硬编码分配
const COLUMN_LAYOUT: ReadonlyArray<ReadonlyArray<string>> = [
  ['实验设定', '反应设定'],
  ['称量设定', '加料设定', '稀释设定'],
  ['内标设定', '闪滤设定'],
]
const ANALYSIS_SECTION_TITLE = '分析方法设定'

const sectionColumns = computed<Array<Array<{ title: string; items: ParamRowEntry[] }>>>(() => {
  const map = new Map(sectionGroups.value.map((g) => [g.title, g]))
  return COLUMN_LAYOUT.map((titles) => {
    return titles
      .map((title) => map.get(title))
      .filter((group): group is { title: string; items: ParamRowEntry[] } => group !== undefined)
  })
})

// 分析方法设定单独占整行, 内部三个分析方法横向排列
const analysisGroup = computed<{ title: string; items: ParamRowEntry[] } | null>(() => {
  return sectionGroups.value.find((g) => g.title === ANALYSIS_SECTION_TITLE) ?? null
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
        <div
          v-for="(column, columnIndex) in sectionColumns"
          :key="columnIndex"
          class="param-column"
        >
          <div v-for="group in column" :key="group.title" class="param-group">
            <h4 class="param-title">{{ group.title }}</h4>
            <el-descriptions :column="1" border size="small" class="param-desc">
              <el-descriptions-item
                v-for="item in group.items"
                :key="item.row + ':' + item.name"
                :label="item.name"
              >
                {{ formatValue(item.value) }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </div>
      </section>
      <section v-if="analysisGroup !== null" class="param-group analysis-group">
        <h4 class="param-title">{{ analysisGroup.title }}</h4>
        <el-descriptions :column="isMobile === true ? 1 : 3" border size="small" class="param-desc analysis-desc">
          <el-descriptions-item
            v-for="item in analysisGroup.items"
            :key="item.row + ':' + item.name"
            :label="item.name"
          >
            {{ formatValue(item.value) }}
          </el-descriptions-item>
        </el-descriptions>
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
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  align-items: start;
}

.param-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
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
  width: 160px;
  white-space: nowrap;
}

.experiment-area {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
}

@media (max-width: 767.98px) {
  .param-area {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .param-column {
    gap: 10px;
  }

  .param-group,
  .experiment-area {
    padding: 10px;
  }

  .param-desc :deep(.el-descriptions__label) {
    width: auto;
    white-space: normal;
  }

  .experiment-area {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
}
</style>
