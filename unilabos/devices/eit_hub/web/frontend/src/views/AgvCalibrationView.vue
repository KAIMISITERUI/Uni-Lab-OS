<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type AgvStatusResponse,
  type MaterialOption,
  type MiddleTrayRow,
  type StationCalibrationOffset,
  type TrayPointOption,
  type TrayPositionRecord,
  applyMiddleTray,
  calibrateStation,
  createTrayPosition,
  deleteTrayPosition,
  fetchAgvStatus,
  fetchMaterials,
  fetchStationOffset,
  fetchTrayOptions,
  fetchTrayPositions,
  previewMiddleTray,
  resetArmCollision,
  testPickTray,
  testPutTray,
  updateTrayPosition,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import JobPanel from '../components/JobPanel.vue'
import TrayCalibrationDialog from '../components/TrayCalibrationDialog.vue'
import StationOffsetDialog from '../components/StationOffsetDialog.vue'
import AllPositionsTestDialog from '../components/AllPositionsTestDialog.vue'
import BatchTransferCycleDialog from '../components/BatchTransferCycleDialog.vue'

interface EditForm {
  name: string
  pose: number[]
  descend_z: number | null
  lift_z: number | null
  drop_z: number | null
  speed: number | null
  acceleration: number | null
  description: string
}

interface CreateForm {
  tray_name: string
  template_tray: string
  pose: number[]
  description: string
}

const status = ref<AgvStatusResponse | null>(null)
const trayOptions = ref<TrayPointOption[]>([])
const materials = ref<MaterialOption[]>([])
const stationOffset = ref<StationCalibrationOffset | null>(null)
const stationOffsetLoading = ref(false)

const testForm = ref<{ tray_name: string; material_type: string; action: 'pick' | 'put' }>({
  tray_name: '',
  material_type: '',
  action: 'pick',
})
const currentJobId = ref('')
const currentJobTitle = ref('运行结果')
const stationLoading = ref(false)

const positions = ref<TrayPositionRecord[]>([])
const positionsLoading = ref(false)
const filterText = ref('')

const editDialogVisible = ref(false)
const editForm = ref<EditForm>(emptyEditForm())
const editBusy = ref(false)

const createDialogVisible = ref(false)
const createForm = ref<CreateForm>(emptyCreateForm())
const createBusy = ref(false)

const middleTrayForm = ref({ station_name: '' })
const middleTrayRows = ref<MiddleTrayRow[]>([])

const filteredPositions = computed(() => {
  const keyword = filterText.value.trim().toLowerCase()
  if (keyword === '') {
    return positions.value
  }
  return positions.value.filter((p) => p.name.toLowerCase().includes(keyword))
})

// 批量物料循环测试需要跨工站选择托盘, 直接由全量点位列表生成
const allTrayOptions = computed<TrayPointOption[]>(() =>
  positions.value.map((p) => ({
    name: p.name,
    label: p.name,
    description: p.description,
    station_id: null,
    station_name: null,
  })),
)

const poseLabels = ['x (mm)', 'y (mm)', 'z (mm)', 'rx (rad)', 'ry (rad)', 'rz (rad)']

function emptyEditForm(): EditForm {
  return {
    name: '',
    pose: [0, 0, 0, 0, 0, 0],
    descend_z: null,
    lift_z: null,
    drop_z: null,
    speed: null,
    acceleration: null,
    description: '',
  }
}

function emptyCreateForm(): CreateForm {
  return {
    tray_name: '',
    template_tray: '',
    pose: [0, 0, 0, 0, 0, 0],
    description: '',
  }
}

const trayDialogVisible = ref(false)
const stationOffsetDialogVisible = ref(false)
const allPositionsDialogVisible = ref(false)
const batchCycleDialogVisible = ref(false)

let statusTimer: number | undefined

const connections = computed(() => status.value?.connections ?? { chassis_connected: false, arm_connected: false })
const isChassisConnected = computed(() => connections.value.chassis_connected === true)
const isArmConnected = computed(() => connections.value.arm_connected === true)
const currentStation = computed(() => status.value?.station ?? null)
const currentStationName = computed(() => currentStation.value?.station_name ?? '')
const collisionInfo = computed(() => status.value?.collision ?? { active: false, axis: null })
const isCollisionActive = computed(() => collisionInfo.value.active === true)
const resetCollisionLoading = ref(false)

async function handleResetCollision() {
  if (resetCollisionLoading.value === true) {
    return
  }
  resetCollisionLoading.value = true
  try {
    await resetArmCollision()
    ElMessage.success('已发送碰撞复位指令')
    // 立即刷新状态, 避免下一次定时轮询前按钮和告警仍残留
    await loadStatus()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    resetCollisionLoading.value = false
  }
}

async function loadStatus() {
  try {
    status.value = await fetchAgvStatus()
  } catch (error) {
    // 静默忽略, 避免轮询失败打扰用户
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  loadStatus()
  statusTimer = window.setInterval(loadStatus, 2000)
}

function stopAutoRefresh() {
  if (statusTimer !== undefined) {
    window.clearInterval(statusTimer)
    statusTimer = undefined
  }
}

async function loadTrayOptions() {
  try {
    const stationId = status.value?.station?.station_id ?? null
    const data = await fetchTrayOptions(stationId)
    trayOptions.value = data.options
  } catch (error) {
    trayOptions.value = []
  }
}

async function loadMaterials() {
  try {
    materials.value = await fetchMaterials()
  } catch (error) {
    materials.value = []
  }
}

async function loadStationOffset() {
  if (currentStationName.value === '') {
    stationOffset.value = null
    return
  }
  stationOffsetLoading.value = true
  try {
    const data = await fetchStationOffset(currentStationName.value)
    stationOffset.value = data.offset
  } catch (error) {
    stationOffset.value = null
  } finally {
    stationOffsetLoading.value = false
  }
}

watch(currentStationName, () => {
  loadStationOffset()
  loadTrayOptions()
})

async function handleTestExecute() {
  const trayName = testForm.value.tray_name.trim()
  if (trayName === '') {
    ElMessage.warning('请选择目标托盘')
    return
  }
  const materialType = testForm.value.material_type === '' ? null : testForm.value.material_type
  try {
    const resp =
      testForm.value.action === 'pick'
        ? await testPickTray({ tray_name: trayName, material_type: materialType })
        : await testPutTray({ tray_name: trayName, material_type: materialType })
    currentJobId.value = resp.job_id
    currentJobTitle.value = testForm.value.action === 'pick' ? '取托盘任务' : '放托盘任务'
    ElMessage.success('任务已提交')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function handleStationCalibrate() {
  if (stationLoading.value === true) {
    return
  }
  stationLoading.value = true
  try {
    const resp = await calibrateStation()
    currentJobId.value = resp.job_id
    currentJobTitle.value = '工站点位校准'
    ElMessage.success('工站点位校准已启动')
  } catch (error) {
    stationLoading.value = false
    ElMessage.error(getErrorMessage(error))
  }
}

function handleJobFinished() {
  if (stationLoading.value === true) {
    stationLoading.value = false
    loadStationOffset()
  }
}

function formatPose(pose: number[] | null | undefined): string {
  if (pose === null || pose === undefined) {
    return '--'
  }
  return pose
    .map((value, index) => (index < 3 ? value.toFixed(3) : `${((value * 180) / Math.PI).toFixed(2)}°`))
    .join('  ')
}

function formatJoints(joints: number[] | null | undefined): string {
  if (joints === null || joints === undefined) {
    return '--'
  }
  return joints.map((value, index) => `J${index + 1}: ${((value * 180) / Math.PI).toFixed(2)}°`).join('  ')
}

function formatOffsetValue(value: number, isAngle: boolean): string {
  return isAngle ? value.toFixed(6) : value.toFixed(3)
}

function openTrayDialog() {
  trayDialogVisible.value = true
}

function openStationOffsetDialog() {
  stationOffsetDialogVisible.value = true
}

function openAllPositionsDialog() {
  allPositionsDialogVisible.value = true
}

function openBatchCycleDialog() {
  batchCycleDialogVisible.value = true
}

function handleTestStarted(jobId: string, title: string) {
  // 弹窗成功提交后, 把 Job ID 交给 JobPanel 实时展示控制器日志
  currentJobId.value = jobId
  currentJobTitle.value = title
}

function handleStationOffsetDialogApplied() {
  loadStationOffset()
  loadPositions()
}

async function loadPositions() {
  positionsLoading.value = true
  try {
    positions.value = await fetchTrayPositions()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    positionsLoading.value = false
  }
}

function openEditDialog(row: TrayPositionRecord) {
  editForm.value = {
    name: row.name,
    pose: row.pose !== null ? [...row.pose] : [0, 0, 0, 0, 0, 0],
    descend_z: row.descend_z,
    lift_z: row.lift_z,
    drop_z: row.drop_z,
    speed: row.speed,
    acceleration: row.acceleration,
    description: row.description ?? '',
  }
  editDialogVisible.value = true
}

async function handleSaveEdit() {
  editBusy.value = true
  try {
    await updateTrayPosition(editForm.value.name, {
      pose: editForm.value.pose,
      descend_z: editForm.value.descend_z ?? undefined,
      lift_z: editForm.value.lift_z ?? undefined,
      drop_z: editForm.value.drop_z ?? undefined,
      speed: editForm.value.speed ?? undefined,
      acceleration: editForm.value.acceleration ?? undefined,
      description: editForm.value.description,
    })
    ElMessage.success('已保存')
    editDialogVisible.value = false
    await loadPositions()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    editBusy.value = false
  }
}

async function handleDeletePosition(row: TrayPositionRecord) {
  try {
    await ElMessageBox.confirm(`确认删除点位 ${row.name}? 该操作会修改 yaml 配置文件.`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deleteTrayPosition(row.name)
    ElMessage.success(`已删除 ${row.name}`)
    await loadPositions()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}

function openCreateDialog() {
  createForm.value = emptyCreateForm()
  if (positions.value.length > 0) {
    createForm.value.template_tray = positions.value[0].name
  }
  createDialogVisible.value = true
}

async function handleCreate() {
  if (createForm.value.tray_name.trim() === '' || createForm.value.template_tray === '') {
    ElMessage.warning('请填写点位名称并选择模板')
    return
  }
  createBusy.value = true
  try {
    await createTrayPosition({
      tray_name: createForm.value.tray_name.trim(),
      template_tray: createForm.value.template_tray,
      pose: createForm.value.pose,
      description: createForm.value.description === '' ? undefined : createForm.value.description,
    })
    ElMessage.success('已创建')
    createDialogVisible.value = false
    await loadPositions()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    createBusy.value = false
  }
}

async function handlePreviewMiddleTray() {
  const stationName = middleTrayForm.value.station_name.trim()
  if (stationName === '') {
    ElMessage.warning('请填写工站名称')
    return
  }
  try {
    const resp = await previewMiddleTray(stationName)
    middleTrayRows.value = resp.rows
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}

async function handleApplyMiddleTray() {
  const stationName = middleTrayForm.value.station_name.trim()
  if (stationName === '') {
    ElMessage.warning('请填写工站名称')
    return
  }
  try {
    await ElMessageBox.confirm(`确认将中间托盘计算结果应用到 ${stationName} 的配置文件?`, '确认应用', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const resp = await applyMiddleTray(stationName)
    ElMessage.success(`已更新 ${resp.updated_count}, 新增 ${resp.created_count}`)
    await loadPositions()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}

function formatPoseShort(pose: number[] | null): string {
  if (pose === null) {
    return '--'
  }
  return pose.map((value, index) => (index < 3 ? value.toFixed(2) : value.toFixed(4))).join(', ')
}

onMounted(() => {
  startAutoRefresh()
  loadTrayOptions()
  loadMaterials()
  loadPositions()
})
onActivated(() => {
  startAutoRefresh()
  loadTrayOptions()
  loadMaterials()
  loadPositions()
})
onDeactivated(stopAutoRefresh)
onBeforeUnmount(stopAutoRefresh)
</script>

<template>
  <div class="view-stack">
    <!-- 状态条 -->
    <section class="panel status-bar">
      <div class="status-grid">
        <div class="status-item">
          <span class="status-label">当前工站</span>
          <span class="status-value">
            <template v-if="currentStation !== null">
              {{ currentStation.station_id }} · {{ currentStation.station_name }}
              <span class="muted" v-if="currentStation.description">({{ currentStation.description }})</span>
            </template>
            <template v-else>未识别</template>
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">连接状态</span>
          <span class="status-value">
            <el-tag :type="isChassisConnected ? 'success' : 'info'" size="small">
              底盘 {{ isChassisConnected ? '已连接' : '未连接' }}
            </el-tag>
            <el-tag :type="isArmConnected ? 'success' : 'info'" size="small" style="margin-left: 6px">
              机械臂 {{ isArmConnected ? '已连接' : '未连接' }}
            </el-tag>
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">TCP</span>
          <span class="status-value pose-mono">{{ formatPose(status?.tcp_pose) }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">关节</span>
          <span class="status-value pose-mono">{{ formatJoints(status?.joints) }}</span>
        </div>
        <div class="status-item" v-if="isCollisionActive">
          <span class="status-label">安全</span>
          <span class="status-value">
            <el-tag type="danger" size="small">
              机械臂碰撞{{ collisionInfo.axis !== null ? ` (轴 J${collisionInfo.axis + 1})` : '' }}
            </el-tag>
            <el-button
              type="danger"
              size="small"
              :loading="resetCollisionLoading"
              style="margin-left: 8px"
              @click="handleResetCollision"
            >
              复位
            </el-button>
          </span>
        </div>
      </div>
    </section>

    <div class="three-column">
      <!-- 工站点位校准 -->
      <section class="panel operation-panel station-calibration-panel">
        <div class="panel-title">
          <h3>工站点位校准</h3>
        </div>
        <p class="muted panel-lead">运行当前工站的 jspf 示教程序, 读取 TCP 偏移并保存.</p>
        <div class="button-row calibration-action-row">
          <el-button
            type="primary"
            size="default"
            class="station-calibrate-button"
            :loading="stationLoading"
            :disabled="!isChassisConnected || !isArmConnected"
            @click="handleStationCalibrate"
          >执行工站点位校准</el-button>
        </div>
        <div class="offset-card compact-offset-card">
          <div class="offset-card-head">
            <div>
              <div class="info-label">校准偏移量</div>
              <div class="offset-card-caption">TCP 位置与姿态补偿</div>
            </div>
            <el-tag v-if="stationOffset !== null" size="small" type="success">已读取</el-tag>
            <el-tag v-else-if="stationOffsetLoading" size="small" type="info">读取中</el-tag>
            <el-tag v-else size="small" type="warning">未就绪</el-tag>
          </div>
          <div v-if="stationOffsetLoading" class="offset-state">正在读取当前工站偏移量...</div>
          <div v-else-if="stationOffset === null" class="offset-state">尚未校准或工站未识别</div>
          <div v-else class="offset-grid">
            <div class="offset-metric">
              <span class="offset-axis">x</span>
              <strong>{{ formatOffsetValue(stationOffset.x, false) }}</strong>
              <span class="offset-unit">mm</span>
            </div>
            <div class="offset-metric">
              <span class="offset-axis">y</span>
              <strong>{{ formatOffsetValue(stationOffset.y, false) }}</strong>
              <span class="offset-unit">mm</span>
            </div>
            <div class="offset-metric">
              <span class="offset-axis">z</span>
              <strong>{{ formatOffsetValue(stationOffset.z, false) }}</strong>
              <span class="offset-unit">mm</span>
            </div>
            <div class="offset-metric">
              <span class="offset-axis">dx</span>
              <strong>{{ formatOffsetValue(stationOffset.dx, true) }}</strong>
              <span class="offset-unit">rad</span>
            </div>
            <div class="offset-metric">
              <span class="offset-axis">dy</span>
              <strong>{{ formatOffsetValue(stationOffset.dy, true) }}</strong>
              <span class="offset-unit">rad</span>
            </div>
            <div class="offset-metric">
              <span class="offset-axis">dz</span>
              <strong>{{ formatOffsetValue(stationOffset.dz, true) }}</strong>
              <span class="offset-unit">rad</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 取放托盘测试 -->
      <section class="panel operation-panel pick-put-panel">
        <div class="panel-title">
          <h3>取放托盘测试</h3>
        </div>
        <p class="muted panel-lead">选择托盘和动作执行单步取放.</p>
        <el-form size="small" label-position="top" class="pick-put-form">
          <div class="pick-put-fields">
            <el-form-item label="目标托盘">
              <el-select v-model="testForm.tray_name" placeholder="请选择" filterable style="width: 100%">
                <el-option
                  v-for="opt in trayOptions"
                  :key="opt.name"
                  :label="opt.label"
                  :value="opt.name"
                >
                  <span>{{ opt.label }}</span>
                  <span class="muted" style="margin-left: 8px">{{ opt.description }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="物料类型">
              <el-select v-model="testForm.material_type" placeholder="默认 (空)" clearable style="width: 100%">
                <el-option
                  v-for="mat in materials"
                  :key="mat.name"
                  :label="mat.name + (mat.description ? ` (${mat.description})` : '')"
                  :value="mat.name"
                />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="动作" class="action-form-item">
            <div class="action-row pick-put-action-row">
              <el-radio-group v-model="testForm.action" class="action-toggle" size="default">
                <el-radio-button label="pick">取托盘</el-radio-button>
                <el-radio-button label="put">放托盘</el-radio-button>
              </el-radio-group>
              <el-button
                type="primary"
                size="default"
                class="pick-put-execute-button"
                :disabled="!isArmConnected"
                @click="handleTestExecute"
              >
                执行
              </el-button>
            </div>
          </el-form-item>
        </el-form>
      </section>

      <!-- 托盘 / 工站偏差校准 + 点位测试 (同列纵向堆叠) -->
      <div class="column-stack">
        <section class="panel">
          <div class="panel-title">
            <h3>托盘 / 工站偏差校准</h3>
          </div>
          <p class="muted">点击按钮在弹窗中完成"准备 → 微调 → 预览 → 保存"流程.</p>
          <div class="button-row">
            <el-button type="primary" :disabled="!isArmConnected" @click="openTrayDialog">
              托盘点位校准
            </el-button>
            <el-button type="primary" :disabled="!isArmConnected" @click="openStationOffsetDialog">
              工站整体偏差校准
            </el-button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">
            <h3>点位测试</h3>
          </div>
          <p class="muted">在弹窗中配置参数后启动测试, 执行日志在下方任务输出栏实时显示.</p>
          <div class="button-row">
            <el-button type="warning" :disabled="!isArmConnected" @click="openAllPositionsDialog">
              全点位测试
            </el-button>
            <el-button type="warning" :disabled="!isArmConnected" @click="openBatchCycleDialog">
              批量物料转运循环测试
            </el-button>
          </div>
        </section>
      </div>
    </div>

    <JobPanel
      v-if="currentJobId !== ''"
      :job-id="currentJobId"
      source="agv"
      :title="currentJobTitle"
      @finished="handleJobFinished"
    />

    <TrayCalibrationDialog
      v-model:visible="trayDialogVisible"
      :tray-options="trayOptions"
      :tcp-pose="status?.tcp_pose ?? null"
      :joints="status?.joints ?? null"
      @saved="loadPositions"
    />
    <StationOffsetDialog
      v-model:visible="stationOffsetDialogVisible"
      :tray-options="trayOptions"
      :current-station-name="currentStationName"
      :tcp-pose="status?.tcp_pose ?? null"
      :joints="status?.joints ?? null"
      @applied="handleStationOffsetDialogApplied"
    />
    <AllPositionsTestDialog
      v-model:visible="allPositionsDialogVisible"
      :materials="materials"
      :current-station-name="currentStationName"
      @started="handleTestStarted"
    />
    <BatchTransferCycleDialog
      v-model:visible="batchCycleDialogVisible"
      :tray-options="allTrayOptions"
      :materials="materials"
      @started="handleTestStarted"
    />

    <!-- 点位管理 -->
    <section class="panel">
      <div class="panel-title">
        <h3>点位管理</h3>
        <div class="button-row">
          <el-input
            v-model="filterText"
            placeholder="筛选点位名称"
            size="small"
            clearable
            style="width: 220px"
          />
          <el-button type="primary" size="small" @click="openCreateDialog">新增点位</el-button>
          <el-button size="small" @click="loadPositions">刷新</el-button>
        </div>
      </div>
      <el-table
        v-loading="positionsLoading"
        :data="filteredPositions"
        size="small"
        stripe
        border
        max-height="540"
      >
        <el-table-column label="名称" prop="name" min-width="180" fixed />
        <el-table-column label="pose [x,y,z,rx,ry,rz]" min-width="320">
          <template #default="{ row }">{{ formatPoseShort(row.pose) }}</template>
        </el-table-column>
        <el-table-column label="descend_z" prop="descend_z" width="100" />
        <el-table-column label="lift_z" prop="lift_z" width="80" />
        <el-table-column label="drop_z" prop="drop_z" width="80" />
        <el-table-column label="speed" prop="speed" width="80" />
        <el-table-column label="acc" prop="acceleration" width="80" />
        <el-table-column label="描述" prop="description" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="handleDeletePosition(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 中间托盘自动计算 -->
    <section class="panel">
      <div class="panel-title">
        <h3>中间托盘自动计算</h3>
      </div>
      <p class="muted">
        给定工站名称, 后端会基于行内已有的左右托盘点位线性插值出中间列, 预览无误后再应用到 yaml.
      </p>
      <el-form size="small" label-width="90px" inline>
        <el-form-item label="工站名称">
          <el-input v-model="middleTrayForm.station_name" placeholder="例如 synthesis_station" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button @click="handlePreviewMiddleTray">预览</el-button>
          <el-button type="primary" @click="handleApplyMiddleTray">应用</el-button>
        </el-form-item>
      </el-form>
      <el-table v-if="middleTrayRows.length > 0" :data="middleTrayRows" size="small" stripe>
        <el-table-column label="行" prop="row_index" width="50" />
        <el-table-column label="目标托盘" prop="target_tray" />
        <el-table-column label="左" prop="left_tray" />
        <el-table-column label="右" prop="right_tray" />
        <el-table-column label="比例" prop="ratio" width="70">
          <template #default="{ row }">
            {{ Number(row.ratio).toFixed(2) }}
          </template>
        </el-table-column>
        <el-table-column label="存在" prop="exists" width="60">
          <template #default="{ row }">
            <el-tag :type="row.exists ? 'success' : 'warning'" size="small">
              {{ row.exists ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 编辑点位弹窗 -->
    <el-dialog v-model="editDialogVisible" title="编辑点位" width="640px" :close-on-click-modal="false">
      <el-form size="small" label-width="120px">
        <el-form-item label="名称">
          <el-input v-model="editForm.name" disabled />
        </el-form-item>
        <el-form-item v-for="(_, idx) in editForm.pose" :key="idx" :label="poseLabels[idx]">
          <el-input-number
            v-model="editForm.pose[idx]"
            :precision="idx < 3 ? 3 : 6"
            :step="idx < 3 ? 0.5 : 0.001"
            controls-position="right"
            style="width: 220px"
          />
        </el-form-item>
        <el-form-item label="descend_z">
          <el-input-number v-model="editForm.descend_z" :precision="2" controls-position="right" style="width: 220px" />
        </el-form-item>
        <el-form-item label="lift_z">
          <el-input-number v-model="editForm.lift_z" :precision="2" controls-position="right" style="width: 220px" />
        </el-form-item>
        <el-form-item label="drop_z">
          <el-input-number v-model="editForm.drop_z" :precision="2" controls-position="right" style="width: 220px" />
        </el-form-item>
        <el-form-item label="speed">
          <el-input-number v-model="editForm.speed" :precision="2" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 220px" />
        </el-form-item>
        <el-form-item label="acceleration">
          <el-input-number v-model="editForm.acceleration" :precision="2" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 220px" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editBusy" @click="handleSaveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增点位弹窗 -->
    <el-dialog v-model="createDialogVisible" title="新增点位" width="640px" :close-on-click-modal="false">
      <el-form size="small" label-width="120px">
        <el-form-item label="点位名称">
          <el-input v-model="createForm.tray_name" placeholder="例如 shelf_tray_1-5" />
        </el-form-item>
        <el-form-item label="模板点位">
          <el-select v-model="createForm.template_tray" filterable placeholder="选择继承非 pose 字段的模板">
            <el-option
              v-for="p in positions"
              :key="p.name"
              :label="p.name"
              :value="p.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-for="(_, idx) in createForm.pose" :key="idx" :label="poseLabels[idx]">
          <el-input-number
            v-model="createForm.pose[idx]"
            :precision="idx < 3 ? 3 : 6"
            :step="idx < 3 ? 0.5 : 0.001"
            controls-position="right"
            style="width: 220px"
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createBusy" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.status-bar {
  padding: 14px 16px;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px 24px;
}
.status-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.status-label {
  color: #5d6d83;
  font-size: 12px;
  font-weight: 600;
}
.status-value {
  color: #1f2c40;
  font-size: 14px;
  font-weight: 600;
}
.pose-mono {
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  font-weight: 500;
}
.info-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
}
.info-label {
  color: #5d6d83;
  font-size: 13px;
  font-weight: 600;
}
.info-value {
  color: #1f2c40;
  font-weight: 600;
}
.operation-panel {
  min-height: 0;
  padding-top: 16px;
  padding-bottom: 16px;
}
.panel-lead {
  margin-bottom: 10px;
  line-height: 1.4;
}
.offset-card {
  margin: 12px 0;
  padding: 10px 12px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}
.compact-offset-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 10px 0 12px;
  padding: 10px 12px;
}
.offset-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.offset-card-caption {
  margin-top: 2px;
  color: #738196;
  font-size: 12px;
}
.offset-state {
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  color: #5d6d83;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
  background: #ffffff;
  border: 1px dashed #cfdbe9;
  border-radius: 6px;
}
.offset-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
  margin-top: 0;
  color: #1f2c40;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}
.offset-metric {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 6px;
}
.offset-axis {
  flex: 0 0 auto;
  color: #5d6d83;
  font-family: Arial, sans-serif;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.offset-metric strong {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #12325a;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.offset-unit {
  flex: 0 0 auto;
  color: #738196;
  font-size: 11px;
}
.calibration-action-row {
  padding-top: 0;
  margin-bottom: 10px;
}
.station-calibrate-button {
  min-width: 172px;
}
.pick-put-form {
  display: flex;
  flex: 1;
  flex-direction: column;
}
.pick-put-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.pick-put-form :deep(.el-form-item) {
  margin-bottom: 10px;
}
.pick-put-fields {
  margin-bottom: 8px;
}
.pick-put-form :deep(.el-form-item__label) {
  padding-bottom: 4px;
  color: #34445d;
  font-size: 12px;
  font-weight: 700;
}
.pick-put-form :deep(.el-select__wrapper) {
  min-height: 34px;
}
.action-form-item {
  margin-top: 0;
  margin-bottom: 0;
}
.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.pick-put-action-row {
  width: 100%;
  align-items: stretch;
  padding: 8px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}
.action-toggle {
  display: grid;
  flex: 1 1 220px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  min-width: 220px;
}
.action-toggle :deep(.el-radio-button) {
  min-width: 0;
}
.action-toggle :deep(.el-radio-button__inner) {
  width: 100%;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.pick-put-execute-button {
  min-width: 84px;
  height: 34px;
}
.column-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.three-column {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  align-items: stretch;
  min-width: 0;
}
/* 面板使用 flex 列, 按钮行贴底, 让三列下沿对齐, 不在面板中部留下大片彩色空白 */
.three-column > .panel,
.three-column > .column-stack > .panel {
  display: flex;
  flex-direction: column;
}
.three-column > .panel .button-row {
  margin-top: auto;
}
.three-column > .pick-put-panel .button-row {
  margin-top: 0;
}
.three-column > .station-calibration-panel .calibration-action-row {
  justify-content: flex-start;
  margin-top: 0;
}
/* 面板标题下方说明文字紧贴标题, 抵消浏览器默认 <p> 的 margin-top */
.three-column .panel > .panel-title {
  margin-bottom: 6px;
}
.three-column .panel > .panel-title + p,
.three-column .panel > .muted {
  margin-top: 0;
}
@media (max-width: 1180px) {
  .three-column {
    grid-template-columns: 1fr;
  }
  .operation-panel {
    min-height: 0;
  }
}
@media (max-width: 720px) {
  .offset-grid,
  .pick-put-fields {
    grid-template-columns: 1fr;
  }
  .action-toggle {
    flex-basis: 100%;
    min-width: 0;
  }
  .pick-put-execute-button {
    width: 100%;
  }
}
</style>
