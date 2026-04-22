<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Box,
  CircleCheck,
  Connection,
  DocumentChecked,
  Download,
  Minus,
  Plus,
  Refresh,
  Upload,
  VideoPlay,
} from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type DashboardData,
  type JobState,
  type ReactionTemplate,
  checkResource,
  fetchDashboard,
  fetchReactionTemplate,
  runSynthesisAction,
  saveReactionTemplate,
  submitReactionTemplate,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'

const activeTab = ref('overview')
const dashboard = ref<DashboardData | null>(null)
const templateData = ref<ReactionTemplate | null>(null)
const currentJobId = ref('')
const dashboardLoading = ref(false)
const templateLoading = ref(false)
const actionLoading = ref('')
const chemicalLoading = ref(false)
const chemicalOptions = ref<ChemicalRow[]>([])
let dashboardTimer: number | undefined

const actionParams = reactive({
  task_id: '',
  water_limit_ppm: 10,
  oxygen_limit_ppm: 10,
})

const stationStateText = computed(() => stateLabel(dashboard.value?.station_state ?? null))

const dashboardErrors = computed(() => {
  if (dashboard.value === null) {
    return []
  }
  return Object.entries(dashboard.value.errors || {}).map(([key, value]) => `${key}: ${value}`)
})

const reagentPairCount = computed(() => templateData.value?.reagent_pair_count || 0)

async function loadDashboard() {
  dashboardLoading.value = true
  try {
    dashboard.value = await fetchDashboard()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    dashboardLoading.value = false
  }
}

async function loadTemplate() {
  templateLoading.value = true
  try {
    templateData.value = await fetchReactionTemplate()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    templateLoading.value = false
  }
}

async function searchChemicals(query: string) {
  chemicalLoading.value = true
  try {
    const data = await listChemicals({
      q: query.trim() !== '' ? query.trim() : undefined,
      query_type: 'name',
      page: 1,
      page_size: 30,
    })
    chemicalOptions.value = data.items
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    chemicalLoading.value = false
  }
}

async function saveTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    templateData.value = await saveReactionTemplate(templateData.value)
    ElMessage.success('模板已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function submitTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await submitReactionTemplate(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('提交任务已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function runResourceCheck() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await checkResource(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('物料核算已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function runAction(actionName: string) {
  actionLoading.value = actionName
  try {
    const data = await runSynthesisAction(actionName, buildActionParams(actionName))
    currentJobId.value = data.job_id
    ElMessage.success('动作已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

function buildActionParams(actionName: string): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  const taskActions = new Set([
    'start_task',
    'wait_task',
    'batch_out_task_empty',
    'run_analysis',
    'poll_analysis',
    'print_task_number_labels',
  ])
  if (taskActions.has(actionName) && actionParams.task_id.trim() !== '') {
    params.task_id = actionParams.task_id.trim()
  }
  if (actionName === 'start_task') {
    params.water_limit_ppm = actionParams.water_limit_ppm
    params.oxygen_limit_ppm = actionParams.oxygen_limit_ppm
    params.check_glovebox_env = true
  }
  return params
}

function onJobFinished(_job: JobState) {
  loadDashboard()
}

function stateLabel(code: number | null): string {
  const map: Record<number, string> = {
    0: '空闲',
    1: '运行中',
    3: '已暂停',
    6: '暂停中',
    7: '停止中',
    10: '挂起',
  }
  if (code === null) {
    return '未知'
  }
  return map[code] || `未知(${code})`
}

function statusTagType(code: unknown): 'success' | 'warning' | 'danger' | 'info' {
  if (code === 0 || code === 'AVAILABLE') {
    return 'success'
  }
  if (code === 1 || code === 'RUNNING') {
    return 'warning'
  }
  if (code === 2 || code === 'UNAVAILABLE') {
    return 'danger'
  }
  return 'info'
}

function formatValue(value: unknown, suffix = ''): string {
  if (value === null || value === undefined || value === '') {
    return '--'
  }
  return `${value}${suffix}`
}

function isYesNoParam(name: string): boolean {
  return ['等待目标温度', '固定加料顺序', '自动加磁子'].includes(name)
}

function isReactorParam(name: string): boolean {
  return name === '反应器类型'
}

function setExperimentCount(count: number) {
  if (templateData.value === null) {
    return
  }
  const width = templateData.value.headers.length
  const nextRows: unknown[][] = []
  for (let index = 0; index < count; index += 1) {
    const source = templateData.value.rows[index]
    const row = Array.isArray(source) ? [...source] : []
    while (row.length < width) {
      row.push('')
    }
    row[0] = index + 1
    nextRows.push(row.slice(0, width))
  }
  templateData.value.rows = nextRows
}

function addReagentPair() {
  if (templateData.value === null) {
    return
  }
  templateData.value.headers.push('试剂', '试剂量')
  for (const row of templateData.value.rows) {
    row.push('', '')
  }
  templateData.value.reagent_pair_count += 1
}

function removeReagentPair() {
  if (templateData.value === null) {
    return
  }
  if (templateData.value.reagent_pair_count <= 1) {
    ElMessage.warning('至少保留一组试剂列')
    return
  }
  templateData.value.headers.splice(templateData.value.headers.length - 2, 2)
  for (const row of templateData.value.rows) {
    row.splice(row.length - 2, 2)
  }
  templateData.value.reagent_pair_count -= 1
}

function isReagentNameColumn(header: string, index: number): boolean {
  if (index === 0) {
    return false
  }
  return header.includes('试剂') && header.includes('量') === false
}

const actions = [
  { name: 'upload_task_flow', label: '上传任务流程', icon: Upload, type: 'primary' },
  { name: 'sync_chemicals', label: '同步化学品库', icon: Connection, type: '' },
  { name: 'batch_in_agv', label: 'AGV 上料', icon: Download, type: '' },
  { name: 'start_task', label: '启动任务', icon: VideoPlay, type: 'success' },
  { name: 'wait_task', label: '等待完成', icon: CircleCheck, type: '' },
  { name: 'batch_out_task_empty', label: '任务下料', icon: Box, type: '' },
  { name: 'auto_unload_to_agv', label: 'AGV 下料', icon: Download, type: '' },
  { name: 'run_analysis', label: '提交分析', icon: DocumentChecked, type: '' },
  { name: 'poll_analysis', label: '谱图处理', icon: Refresh, type: '' },
]

onMounted(() => {
  loadDashboard()
  dashboardTimer = window.setInterval(loadDashboard, 5000)
})

onBeforeUnmount(() => {
  if (dashboardTimer !== undefined) {
    window.clearInterval(dashboardTimer)
  }
})
</script>

<template>
  <div class="view-stack">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="总览" name="overview">
        <div class="view-stack">
          <section class="metrics-grid">
            <div class="metric">
              <div class="metric-label">工站状态</div>
              <div class="metric-value">{{ stationStateText }}</div>
              <div class="metric-note">实时轮询</div>
            </div>
            <div class="metric">
              <div class="metric-label">水含量</div>
              <div class="metric-value">
                {{ formatValue(dashboard?.glovebox_env?.water_content, ' ppm') }}
              </div>
              <div class="metric-note">手套箱</div>
            </div>
            <div class="metric">
              <div class="metric-label">氧含量</div>
              <div class="metric-value">
                {{ formatValue(dashboard?.glovebox_env?.oxygen_content, ' ppm') }}
              </div>
              <div class="metric-note">手套箱</div>
            </div>
            <div class="metric">
              <div class="metric-label">箱压</div>
              <div class="metric-value">
                {{ formatValue(dashboard?.glovebox_env?.box_pressure) }}
              </div>
              <div class="metric-note">环境监测</div>
            </div>
          </section>

          <el-alert
            v-for="errorText in dashboardErrors"
            :key="errorText"
            type="error"
            :title="errorText"
            :closable="false"
          />

          <section class="panel">
            <div class="panel-title">
              <h2>站内资源</h2>
              <el-button :icon="Refresh" :loading="dashboardLoading" @click="loadDashboard">
                刷新
              </el-button>
            </div>
            <div class="table-wrap">
              <el-table :data="dashboard?.resources || []" border stripe height="360">
                <el-table-column prop="layout_code" label="位置" width="120" />
                <el-table-column prop="resource_type_name" label="托盘类型" min-width="180" />
                <el-table-column prop="count" label="数量" width="90" align="center" />
                <el-table-column label="物质详情" min-width="260">
                  <template #default="{ row }">
                    <span>
                      {{
                        (row.substance_details || [])
                          .map((item: Record<string, unknown>) => item.substance)
                          .filter(Boolean)
                          .join(', ') || '--'
                      }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </section>

          <section class="two-column">
            <div class="panel">
              <div class="panel-title">
                <h3>设备状态</h3>
              </div>
              <el-table :data="dashboard?.device_status || []" border stripe height="300">
                <el-table-column prop="device_name" label="设备" min-width="140" />
                <el-table-column label="状态" width="120" align="center">
                  <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status_code)">
                      {{ row.status || row.status_code }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="panel">
              <div class="panel-title">
                <h3>最近任务</h3>
              </div>
              <el-table :data="dashboard?.recent_tasks || []" border stripe height="300">
                <el-table-column prop="task_id" label="任务 ID" width="100" />
                <el-table-column prop="task_name" label="任务名称" min-width="180" />
                <el-table-column prop="status" label="状态码" width="100" align="center" />
              </el-table>
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="流程操作" name="actions">
        <div class="view-stack">
          <section class="panel">
            <div class="panel-title">
              <h2>工站动作</h2>
            </div>
            <el-form label-position="top">
              <div class="action-params">
                <el-form-item label="任务 ID">
                  <el-input v-model="actionParams.task_id" placeholder="留空时由底层逻辑自动选择" />
                </el-form-item>
                <el-form-item label="水含量阈值 ppm">
                  <el-input-number v-model="actionParams.water_limit_ppm" :min="0" />
                </el-form-item>
                <el-form-item label="氧含量阈值 ppm">
                  <el-input-number v-model="actionParams.oxygen_limit_ppm" :min="0" />
                </el-form-item>
              </div>
            </el-form>
            <div class="action-grid">
              <el-button
                v-for="action in actions"
                :key="action.name"
                :type="action.type"
                :icon="action.icon"
                :loading="actionLoading === action.name"
                @click="runAction(action.name)"
              >
                {{ action.label }}
              </el-button>
            </div>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.param-panel {
  display: grid;
  gap: 4px;
  min-width: 0;
  max-height: 680px;
  overflow: auto;
  padding-right: 4px;
}

.param-section {
  margin-top: 8px;
  padding: 8px 10px;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #eef4fb;
}

.edit-grid {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
}

.edit-grid th,
.edit-grid td {
  width: 168px;
  min-width: 168px;
  padding: 8px;
  border: 1px solid #dce5f0;
  background: #ffffff;
}

.edit-grid th {
  position: sticky;
  top: 0;
  z-index: 1;
  color: #172033;
  font-size: 13px;
  background: #eef4fb;
}

.edit-grid th:first-child,
.edit-grid td:first-child {
  width: 96px;
  min-width: 96px;
  text-align: center;
}

.action-params {
  display: grid;
  grid-template-columns: minmax(180px, 260px) 180px 180px;
  gap: 12px;
  align-items: end;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 12px;
}

.action-grid .el-button {
  justify-content: flex-start;
  height: 44px;
  margin-left: 0;
}

@media (max-width: 860px) {
  .action-params,
  .action-grid {
    grid-template-columns: 1fr;
  }
}
</style>
