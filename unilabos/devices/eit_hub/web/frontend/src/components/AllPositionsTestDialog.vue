<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { type MaterialOption, testAllPositions } from '../api/agv'
import { getErrorMessage } from '../api/http'

const dialogWidth = 'min(560px, 92vw)'

const props = defineProps<{
  visible: boolean
  materials: MaterialOption[]
  currentStationName: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  started: [jobId: string, title: string]
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const materialType = ref('')
const submitting = ref(false)

watch(
  () => props.visible,
  (v) => {
    // 弹窗每次打开都重置选择, 避免上一次输入残留
    if (v === true) {
      materialType.value = ''
      submitting.value = false
    }
  },
)

const stationDisplay = computed(() =>
  props.currentStationName === '' ? '未识别' : props.currentStationName,
)

const submitDisabled = computed(
  () => props.currentStationName === '' || materialType.value === '',
)

async function handleSubmit() {
  if (submitDisabled.value === true) {
    ElMessage.warning('请先识别工站并选择托盘种类')
    return
  }
  submitting.value = true
  try {
    const data = await testAllPositions({ material_type: materialType.value })
    emit('started', data.job_id, '全点位测试')
    ElMessage.success('全点位测试已开始, 请关注下方任务输出')
    dialogVisible.value = false
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    title="全点位测试"
    :width="dialogWidth"
    top="8vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    destroy-on-close
  >
    <p class="muted">
      从 agv_tray_1 取托盘依次放到当前工站每个点位再取回, 测试所有点位的准确性.
    </p>
    <el-form size="small" label-width="100px">
      <el-form-item label="当前工站">
        <span :class="{ muted: props.currentStationName === '' }">{{ stationDisplay }}</span>
      </el-form-item>
      <el-form-item label="托盘种类">
        <el-select
          v-model="materialType"
          placeholder="请选择托盘种类"
          filterable
          style="width: 100%"
        >
          <el-option
            v-for="mat in props.materials"
            :key="mat.name"
            :label="`${mat.name}${mat.description ? ` - ${mat.description}` : ''} (夹爪: ${mat.gripper})`"
            :value="mat.name"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="props.currentStationName === ''"
      type="warning"
      :closable="false"
      title="未识别当前工站, 请先校准或移动到目标工站"
      show-icon
    />
    <el-alert
      type="warning"
      :closable="false"
      title="请确保 agv_tray_1 已放置托盘, 且周围安全, 测试过程会控制机械臂连续动作."
      show-icon
      style="margin-top: 8px"
    />
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        :disabled="submitDisabled"
        @click="handleSubmit"
      >开始测试</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.muted {
  color: var(--el-text-color-secondary);
}
</style>
