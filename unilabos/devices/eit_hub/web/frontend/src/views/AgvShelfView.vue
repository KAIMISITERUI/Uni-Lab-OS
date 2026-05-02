<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type ShelfSlotInfo,
  type ShelfStatusResponse,
  fetchShelfStatus,
  placeShelfMaterial,
  removeShelfSlot,
  resetShelf,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import ShelfGrid from '../components/ShelfGrid.vue'

const shelfStatus = ref<ShelfStatusResponse | null>(null)
const actionLoading = ref('')
const detailDialog = ref(false)
const detailSlot = ref<string>('')
const detailInfo = ref<ShelfSlotInfo | null>(null)
const placeForm = ref({
  slot_name: '',
  material_type: '',
  source: '',
  description: '',
})
const placeDialog = ref(false)

let refreshTimer: number | undefined

async function loadStatus() {
  try {
    const data = await fetchShelfStatus()
    shelfStatus.value = data
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  loadStatus()
  refreshTimer = window.setInterval(loadStatus, 5000)
}

function stopAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

function handleSlotClick(slotName: string, info: ShelfSlotInfo | null) {
  detailSlot.value = slotName
  detailInfo.value = info
  detailDialog.value = true
}

async function handleClearSlot() {
  if (detailSlot.value === '') {
    return
  }
  actionLoading.value = 'remove'
  try {
    await removeShelfSlot(detailSlot.value)
    ElMessage.success('槽位已清空')
    detailDialog.value = false
    await loadStatus()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleResetAll() {
  try {
    await ElMessageBox.confirm('确认清空全部货架槽位? 此操作不可恢复.', '二次确认', {
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  actionLoading.value = 'reset'
  try {
    await resetShelf()
    ElMessage.success('已清空全部槽位')
    await loadStatus()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

function openPlaceDialog(slotName: string) {
  placeForm.value = {
    slot_name: slotName,
    material_type: '',
    source: '',
    description: '',
  }
  placeDialog.value = true
}

async function handlePlace() {
  if (placeForm.value.slot_name.trim() === '' || placeForm.value.material_type.trim() === '') {
    ElMessage.warning('请填写槽位名称和物料类型')
    return
  }
  actionLoading.value = 'place'
  try {
    await placeShelfMaterial({
      slot_name: placeForm.value.slot_name.trim(),
      material_type: placeForm.value.material_type.trim(),
      source: placeForm.value.source.trim(),
      description: placeForm.value.description.trim(),
    })
    ElMessage.success('物料已登记')
    placeDialog.value = false
    await loadStatus()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

onMounted(startAutoRefresh)
onActivated(startAutoRefresh)
onDeactivated(stopAutoRefresh)
onBeforeUnmount(stopAutoRefresh)
</script>

<template>
  <div class="view-stack">
    <section class="panel">
      <div class="panel-title">
        <h2>AGV 货架</h2>
        <div class="button-row shelf-toolbar">
          <span class="muted shelf-last-updated">
            最后更新: {{ shelfStatus?.last_updated || '--' }}
          </span>
          <el-button
            type="danger"
            :loading="actionLoading === 'reset'"
            @click="handleResetAll"
          >清空全部</el-button>
        </div>
      </div>

      <ShelfGrid
        :slots="shelfStatus?.slots ?? {}"
        @slot-click="handleSlotClick"
      />
    </section>

    <el-dialog v-model="detailDialog" :title="`槽位详情 - ${detailSlot}`" width="520px">
      <template v-if="detailInfo !== null">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="物料类型">{{ detailInfo.material_type }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detailInfo.source || '--' }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ detailInfo.description || '--' }}</el-descriptions-item>
          <el-descriptions-item label="放置时间">{{ detailInfo.placed_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template v-else>
        <p class="muted">该槽位为空.</p>
      </template>
      <template #footer>
        <el-button @click="detailDialog = false">关闭</el-button>
        <el-button
          v-if="detailInfo !== null"
          type="danger"
          :loading="actionLoading === 'remove'"
          @click="handleClearSlot"
        >清空此槽</el-button>
        <el-button
          v-else
          type="primary"
          @click="openPlaceDialog(detailSlot)"
        >登记物料</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="placeDialog" :title="`登记物料 - ${placeForm.slot_name}`" width="460px">
      <el-form size="small" label-width="90px">
        <el-form-item label="物料类型" required>
          <el-input v-model="placeForm.material_type" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="placeForm.source" placeholder="例如 analysis_station_tray_1-2" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="placeForm.description" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="placeDialog = false">取消</el-button>
        <el-button type="primary" :loading="actionLoading === 'place'" @click="handlePlace">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.shelf-toolbar {
  align-items: center;
}

.shelf-last-updated {
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

@media (max-width: 767.98px) {
  .shelf-toolbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    width: 100%;
    gap: 10px;
  }

  .shelf-toolbar :deep(.el-button) {
    margin-left: 0;
  }
}
</style>
