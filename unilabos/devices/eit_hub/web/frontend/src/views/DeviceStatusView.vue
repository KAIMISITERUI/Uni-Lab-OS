<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  fetchDeviceStatus,
  type DeviceEndpointStatus,
  type DeviceStatusItem,
  type DeviceStatusResponse,
  type DeviceStatusText,
} from '../api/devices'
import { getErrorMessage } from '../api/http'
import ResponsiveTable from '../components/ResponsiveTable.vue'

// 设备表手机端卡片字段
const deviceCardFields = [
  { key: 'name', label: '设备', primary: true },
  { key: 'category', label: '类别' },
  { key: 'address', label: '地址' },
  { key: 'status', label: '状态' },
  { key: 'summary', label: '端口汇总' },
  { key: 'endpoints', label: '端口明细' },
] as const

interface DeviceStatusStats {
  total: number
  online: number
  partial: number
  offline: number
}

const snapshot = ref<DeviceStatusResponse | null>(null)
const refreshing = ref(false)
let refreshTimer: number | undefined

const items = computed<DeviceStatusItem[]>(() => {
  if (snapshot.value === null) {
    return []
  }
  return snapshot.value.items
})

const stats = computed<DeviceStatusStats>(() => {
  const result: DeviceStatusStats = {
    total: items.value.length,
    online: 0,
    partial: 0,
    offline: 0,
  }
  for (const item of items.value) {
    if (item.status === '在线') {
      result.online += 1
      continue
    }
    if (item.status === '部分在线') {
      result.partial += 1
      continue
    }
    result.offline += 1
  }
  return result
})

const checkedAtText = computed(() => {
  if (snapshot.value === null) {
    return '--'
  }
  return snapshot.value.checked_at
})

const initialLoading = computed(() => refreshing.value === true && snapshot.value === null)

async function refreshDeviceStatus() {
  if (refreshing.value === true) {
    return
  }
  refreshing.value = true
  try {
    snapshot.value = await fetchDeviceStatus()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    refreshing.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshDeviceStatus()
  refreshTimer = window.setInterval(refreshDeviceStatus, 10000)
}

function stopAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

function statusTagType(status: DeviceStatusText): 'success' | 'warning' | 'danger' {
  if (status === '在线') {
    return 'success'
  }
  if (status === '部分在线') {
    return 'warning'
  }
  return 'danger'
}

function endpointTagType(endpoint: DeviceEndpointStatus): 'success' | 'danger' {
  if (endpoint.reachable === true) {
    return 'success'
  }
  return 'danger'
}

function endpointStatusText(endpoint: DeviceEndpointStatus): string {
  if (endpoint.reachable === true) {
    return '在线'
  }
  return '离线'
}

function formatLatency(latencyMs: number | null): string {
  if (latencyMs === null) {
    return '--'
  }
  if (Number.isFinite(latencyMs) === false) {
    return '--'
  }
  return `${latencyMs.toFixed(1)} ms`
}

onActivated(() => {
  startAutoRefresh()
})

onDeactivated(() => {
  stopAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="view-stack device-status-view">
    <section class="panel">
      <div class="panel-title">
        <h2>设备状态</h2>
        <div class="device-toolbar">
          <span class="muted">最后刷新: {{ checkedAtText }}</span>
          <el-button type="primary" :icon="Refresh" :loading="initialLoading" @click="refreshDeviceStatus">
            刷新
          </el-button>
        </div>
      </div>

      <div class="metrics-grid device-metrics">
        <div class="metric">
          <div class="metric-label">设备总数</div>
          <div class="metric-value">{{ stats.total }}</div>
          <div class="metric-note">含 EIT Hub</div>
        </div>
        <div class="metric">
          <div class="metric-label">在线</div>
          <div class="metric-value success-text">{{ stats.online }}</div>
          <div class="metric-note">全部端口可联通</div>
        </div>
        <div class="metric">
          <div class="metric-label">部分在线</div>
          <div class="metric-value warning-text">{{ stats.partial }}</div>
          <div class="metric-note">存在离线端口</div>
        </div>
        <div class="metric">
          <div class="metric-label">离线</div>
          <div class="metric-value danger-text">{{ stats.offline }}</div>
          <div class="metric-note">端口不可联通</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>连接明细</h2>
        <span class="muted">{{ items.length }} 台设备</span>
      </div>

      <div class="table-wrap">
        <ResponsiveTable
          :data="items"
          row-key="key"
          :card-fields="deviceCardFields"
        >
          <el-table :data="items" v-loading="initialLoading" row-key="key">
            <el-table-column label="设备" min-width="160">
              <template #default="{ row }">
                <div class="device-name-cell">
                  <span class="device-name">{{ row.name }}</span>
                  <span class="device-category">{{ row.category }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="address" label="地址" min-width="260" show-overflow-tooltip />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" effect="light">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="端口汇总" width="130" />
            <el-table-column label="端口明细" min-width="340">
              <template #default="{ row }">
                <div class="endpoint-list">
                  <div
                    v-for="endpoint in row.endpoints"
                    :key="`${endpoint.host}:${endpoint.port}`"
                    class="endpoint-row"
                  >
                    <el-tag :type="endpointTagType(endpoint)" size="small" effect="plain">
                      {{ endpointStatusText(endpoint) }}
                    </el-tag>
                    <span class="endpoint-address">{{ endpoint.host }}:{{ endpoint.port }}</span>
                    <span class="endpoint-latency">{{ formatLatency(endpoint.latency_ms) }}</span>
                    <span v-if="endpoint.error !== ''" class="endpoint-error">
                      {{ endpoint.error }}
                    </span>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <template #cell:status="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="light">{{ row.status }}</el-tag>
          </template>
          <template #cell:endpoints="{ row }">
            <div class="endpoint-list">
              <div
                v-for="endpoint in row.endpoints"
                :key="`${endpoint.host}:${endpoint.port}`"
                class="endpoint-row"
              >
                <el-tag :type="endpointTagType(endpoint)" size="small" effect="plain">
                  {{ endpointStatusText(endpoint) }}
                </el-tag>
                <span class="endpoint-address">{{ endpoint.host }}:{{ endpoint.port }}</span>
                <span class="endpoint-latency">{{ formatLatency(endpoint.latency_ms) }}</span>
                <span v-if="endpoint.error !== ''" class="endpoint-error">{{ endpoint.error }}</span>
              </div>
            </div>
          </template>
        </ResponsiveTable>
      </div>
    </section>
  </div>
</template>

<style scoped>
.device-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.device-metrics {
  grid-template-columns: repeat(4, minmax(150px, 1fr));
}

.warning-text {
  color: #b7791f;
}

.device-name-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.device-name {
  color: #172033;
  font-weight: 700;
}

.device-category {
  color: #738196;
  font-size: 12px;
}

.endpoint-list {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.endpoint-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.endpoint-address {
  color: #24344d;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}

.endpoint-latency {
  color: #66758a;
  font-size: 12px;
}

.endpoint-error {
  min-width: 180px;
  color: #d6422b;
  font-size: 12px;
  word-break: break-all;
}

@media (max-width: 767.98px) {
  .device-toolbar {
    justify-content: flex-start;
  }

  /* device-metrics 不再写死列数, 走全局 .metrics-grid 的 auto-fit */
  .device-metrics {
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
  }

  .endpoint-error {
    min-width: 0;
  }

  .endpoint-row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: start;
    gap: 4px 8px;
  }

  .endpoint-address,
  .endpoint-latency,
  .endpoint-error {
    grid-column: 2;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
}
</style>
