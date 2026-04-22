<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type DashboardData,
  type JobState,
  type OuterDoorAction,
  fetchDashboard,
  controlOuterDoor,
  controlW1Shelf,
  initSynthesisDevice,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'
import StructurePreview from '../components/StructurePreview.vue'

interface ReagentOccurrence {
  amount: string
  position: string
  trayType: string
}

interface ReagentDisplayRow {
  substance: string
  structureSmiles: string
  occurrences: ReagentOccurrence[]
}

const dashboard = ref<DashboardData | null>(null)
const currentJobId = ref('')
const dashboardLoading = ref(false)
const actionLoading = ref('')
const reagentStructureMap = ref<Record<string, string>>({})
let dashboardTimer: number | undefined

const w1Params = reactive({
  position: 'W-1-1',
  action: 'outside' as 'outside' | 'home',
})

const reagentResourceTypeCodes = new Set([201000600, 201000730, 201000502, 201000503, 220000023])
const consumableCardConfigs = [
  { resourceType: 201000726, label: '2 mL 反应试管' },
  { resourceType: 201000712, label: '反应密封盖' },
  { resourceType: 201000711, label: '2 mL 试管磁子' },
  { resourceType: 201000512, label: '5 mL Tip 头' },
  { resourceType: 201000731, label: '1 mL Tip 头' },
  { resourceType: 201000815, label: '50 μL Tip 头' },
  { resourceType: 201000727, label: '闪滤瓶内瓶' },
  { resourceType: 201000728, label: '闪滤瓶外瓶' },
]
const w1ShelfPositions = ['W-1-1', 'W-1-3', 'W-1-5', 'W-1-7']
const w1ShelfActions = [
  { label: '推出', value: 'outside' },
  { label: '复位', value: 'home' },
]

const stationStateText = computed(() => stateLabel(dashboard.value?.station_state ?? null))

const dashboardErrors = computed(() => {
  if (dashboard.value === null) {
    return []
  }
  return Object.entries(dashboard.value.errors || {}).map(([key, value]) => `${key}: ${value}`)
})

const visibleDeviceStatus = computed(() => {
  return (dashboard.value?.device_status || []).filter((row) => {
    return row.device_name !== '手套箱箱体环境'
  })
})

const reagentResources = computed(() => {
  return (dashboard.value?.resources || []).filter((row) => isReagentResource(row))
})

const reagentDisplayRows = computed(() => {
  const rowMap = new Map<string, ReagentDisplayRow>()
  for (const resource of reagentResources.value) {
    const details = Array.isArray(resource.substance_details) ? resource.substance_details : []
    for (const item of details) {
      if (typeof item !== 'object' || item === null) {
        continue
      }
      const detail = item as Record<string, unknown>
      const substance = String(detail.substance || '').trim()
      if (substance === '') {
        continue
      }
      const key = normalizeChemicalName(substance)
      if (rowMap.has(key) === false) {
        rowMap.set(key, {
          substance,
          structureSmiles: reagentStructureMap.value[key] || '',
          occurrences: [],
        })
      }
      rowMap.get(key)?.occurrences.push({
        amount: String(detail.value || '--'),
        position: formatReagentPosition(resource, detail),
        trayType: String(resource.resource_type_name || '--'),
      })
    }
  }
  return Array.from(rowMap.values())
})

const consumableCards = computed(() => {
  const countMap = new Map<number, number>()
  for (const row of dashboard.value?.resources || []) {
    const code = Number(row.resource_type)
    if (Number.isFinite(code) === false) {
      continue
    }
    const count = Number(row.count)
    countMap.set(code, (countMap.get(code) || 0) + (Number.isFinite(count) ? count : 0))
  }
  return consumableCardConfigs.map((config) => ({
    ...config,
    count: countMap.get(config.resourceType) || 0,
  }))
})

const outerDoorAction = computed(() => {
  const device = (dashboard.value?.device_status || []).find((row) => row.device_name === '过渡舱外门')
  const status = String(device?.status || '').toUpperCase()
  const statusCode = Number(device?.status_code)
  if (status === 'OPEN' || statusCode === 3) {
    return { action: 'close' as const, label: '关闭外门', type: 'warning' }
  }
  if (status === 'CLOSE' || statusCode === 4) {
    return { action: 'open' as const, label: '打开外门', type: 'success' }
  }
  return null
})

async function loadDashboard() {
  dashboardLoading.value = true
  try {
    const data = await fetchDashboard()
    dashboard.value = data
    void loadReagentStructures(data.resources || [])
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    dashboardLoading.value = false
  }
}

async function loadReagentStructures(resources: Array<Record<string, unknown>>) {
  const names = collectReagentNames(resources)
  const missingNames = names.filter((name) => {
    return reagentStructureMap.value[normalizeChemicalName(name)] === undefined
  })
  if (missingNames.length === 0) {
    return
  }

  const nextMap = { ...reagentStructureMap.value }
  await Promise.all(
    missingNames.map(async (name) => {
      const key = normalizeChemicalName(name)
      try {
        const response = await listChemicals({
          q: name,
          query_type: 'name',
          page: 1,
          page_size: 10,
        })
        const chemical = pickChemicalByName(name, response.items)
        nextMap[key] = String(chemical?.smiles || '')
      } catch {
        nextMap[key] = ''
      }
    }),
  )
  reagentStructureMap.value = nextMap
}

async function runDeviceInit() {
  actionLoading.value = 'device_init'
  try {
    const data = await initSynthesisDevice()
    currentJobId.value = data.job_id
    ElMessage.success('设备初始化已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function runOuterDoor(action: OuterDoorAction) {
  actionLoading.value = `outer_door_${action}`
  try {
    const data = await controlOuterDoor(action)
    currentJobId.value = data.job_id
    ElMessage.success('外门操作已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function runW1Shelf() {
  actionLoading.value = 'control_w1_shelf'
  try {
    const data = await controlW1Shelf({
      position: w1Params.position,
      action: w1Params.action,
    })
    currentJobId.value = data.job_id
    ElMessage.success('W1 操作已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
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

function formatOneDecimalPpm(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '--'
  }
  const numericValue = Number(value)
  if (Number.isFinite(numericValue) === false) {
    return '--'
  }
  return `${numericValue.toFixed(1)} ppm`
}

function isReagentResource(row: Record<string, unknown>): boolean {
  const code = Number(row.resource_type)
  if (Number.isFinite(code) && reagentResourceTypeCodes.has(code)) {
    return true
  }
  const resourceTypeName = String(row.resource_type_name || '')
  return resourceTypeName.includes('试剂瓶托盘') || resourceTypeName.includes('粉桶托盘')
}

function collectReagentNames(resources: Array<Record<string, unknown>>): string[] {
  const names = new Map<string, string>()
  for (const resource of resources) {
    if (isReagentResource(resource) === false) {
      continue
    }
    const details = Array.isArray(resource.substance_details) ? resource.substance_details : []
    for (const item of details) {
      if (typeof item !== 'object' || item === null) {
        continue
      }
      const substance = String((item as Record<string, unknown>).substance || '').trim()
      if (substance !== '') {
        names.set(normalizeChemicalName(substance), substance)
      }
    }
  }
  return Array.from(names.values())
}

function normalizeChemicalName(value: unknown): string {
  return String(value || '').trim().replace(/\s+/g, '').toLowerCase()
}

function pickChemicalByName(name: string, rows: ChemicalRow[]): ChemicalRow | null {
  const key = normalizeChemicalName(name)
  return (
    rows.find((row) => normalizeChemicalName(row.substance) === key) ||
    rows.find((row) => normalizeChemicalName(row.other_name) === key) ||
    rows[0] ||
    null
  )
}

function formatReagentPosition(
  resource: Record<string, unknown>,
  detail: Record<string, unknown>,
): string {
  const layoutCode = String(resource.layout_code || '--')
  const well = String(detail.well || '').trim()
  if (well === '') {
    return layoutCode
  }
  return `${layoutCode} / ${well}`
}

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
    <section class="metrics-grid">
            <div class="metric">
              <div class="metric-label">工站状态</div>
              <div class="metric-value">{{ stationStateText }}</div>
              <div class="metric-note">实时轮询</div>
            </div>
            <div class="metric">
              <div class="metric-label">水含量</div>
              <div class="metric-value">
                {{ formatOneDecimalPpm(dashboard?.glovebox_env?.water_content) }}
              </div>
              <div class="metric-note">手套箱</div>
            </div>
            <div class="metric">
              <div class="metric-label">氧含量</div>
              <div class="metric-value">
                {{ formatOneDecimalPpm(dashboard?.glovebox_env?.oxygen_content) }}
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
            <div class="resource-stack">
              <div class="resource-group">
                <div class="consumable-card-grid">
                  <div
                    v-for="card in consumableCards"
                    :key="card.resourceType"
                    class="consumable-card"
                  >
                    <div class="consumable-card-content">
                      <div class="consumable-card-label">{{ card.label }}</div>
                      <div class="consumable-card-count">{{ card.count }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="resource-group">
                <div class="table-wrap">
                  <el-table class="reagent-table" :data="reagentDisplayRows" border stripe height="420">
                    <el-table-column label="结构式" width="142" align="center">
                      <template #default="{ row }">
                        <StructurePreview
                          :smiles="row.structureSmiles"
                          :width="118"
                          :height="86"
                        />
                      </template>
                    </el-table-column>
                    <el-table-column prop="substance" label="物质名称" min-width="260" align="center" />
                    <el-table-column label="物质的量" width="140" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.amount }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="位置" width="170" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.position }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="托盘种类" min-width="180" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.trayType }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </div>
          </section>

          <section class="two-column overview-status-actions">
            <div class="panel">
              <div class="panel-title">
                <h3>设备状态</h3>
              </div>
              <div class="device-status-grid">
                <div
                  v-for="device in visibleDeviceStatus"
                  :key="String(device.device_name)"
                  class="device-status-item"
                >
                  <span class="device-status-name">{{ device.device_name }}</span>
                  <el-tag :type="statusTagType(device.status_code)">
                    {{ device.status || device.status_code }}
                  </el-tag>
                </div>
              </div>
            </div>

            <div class="panel">
              <div class="panel-title">
                <h3>其它操作</h3>
              </div>
              <div class="other-actions">
                <el-button
                  class="init-action-button"
                  type="primary"
                  :loading="actionLoading === 'device_init'"
                  @click="runDeviceInit"
                >
                  设备初始化
                </el-button>
                <div class="operation-group">
                  <div class="operation-title">过渡舱外门</div>
                  <div class="operation-row">
                    <el-button
                      v-if="outerDoorAction !== null"
                      :type="outerDoorAction.type"
                      :loading="actionLoading === `outer_door_${outerDoorAction.action}`"
                      @click="runOuterDoor(outerDoorAction.action)"
                    >
                      {{ outerDoorAction.label }}
                    </el-button>
                    <el-button v-else disabled>
                      外门状态未知
                    </el-button>
                  </div>
                </div>
                <div class="operation-group">
                  <div class="operation-title">W1 排货架</div>
                  <el-form label-position="top">
                    <div class="w1-form">
                      <el-form-item label="位置">
                        <el-select v-model="w1Params.position">
                          <el-option
                            v-for="position in w1ShelfPositions"
                            :key="position"
                            :label="position"
                            :value="position"
                          />
                        </el-select>
                      </el-form-item>
                      <el-form-item label="动作">
                        <el-select v-model="w1Params.action">
                          <el-option
                            v-for="action in w1ShelfActions"
                            :key="action.value"
                            :label="action.label"
                            :value="action.value"
                          />
                        </el-select>
                      </el-form-item>
                      <el-button
                        class="w1-execute-button"
                        :loading="actionLoading === 'control_w1_shelf'"
                        @click="runW1Shelf"
                      >
                        执行 W1 操作
                      </el-button>
                    </div>
                  </el-form>
                </div>
              </div>
            </div>
          </section>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.resource-stack {
  display: grid;
  gap: 18px;
  min-width: 0;
}

.resource-group {
  display: grid;
  min-width: 0;
}

.consumable-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(188px, 1fr));
  gap: 12px;
}

.consumable-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  min-height: 88px;
  padding: 16px 18px;
  background: #f3f8ff;
  border: 1px solid #e3ebf8;
  border-radius: 8px;
}

.consumable-card-content {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.consumable-card-label {
  overflow: hidden;
  color: #738196;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.consumable-card-count {
  color: #172033;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.reagent-occurrence-list {
  display: grid;
  gap: 4px;
  justify-items: center;
  color: #24344d;
  line-height: 1.45;
  text-align: center;
}

.reagent-table :deep(.cell) {
  display: flex;
  justify-content: center;
}

.overview-status-actions {
  grid-template-columns: minmax(560px, 1.35fr) minmax(320px, 0.65fr);
}

.device-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 10px;
  max-height: 300px;
  overflow: auto;
}

.device-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  min-height: 42px;
  padding: 8px 10px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}

.device-status-name {
  overflow: hidden;
  color: #24344d;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.other-actions {
  display: grid;
  gap: 14px;
}

.other-actions .el-button {
  justify-content: flex-start;
  min-height: 40px;
  margin-left: 0;
}

.init-action-button,
.operation-row .el-button,
.w1-execute-button {
  justify-content: center !important;
}

.operation-group {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.operation-title {
  color: #34445d;
  font-size: 13px;
  font-weight: 700;
}

.operation-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.w1-form {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(120px, 1fr) minmax(128px, 0.8fr);
  gap: 10px;
  align-items: end;
}

.w1-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.w1-execute-button {
  width: 100%;
  min-height: 32px;
}

@media (max-width: 860px) {
  .overview-status-actions,
  .device-status-grid,
  .operation-row,
  .w1-form {
    grid-template-columns: 1fr;
  }
}
</style>
