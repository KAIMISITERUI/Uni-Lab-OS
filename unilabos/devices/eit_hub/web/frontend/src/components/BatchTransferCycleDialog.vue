<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  type BatchTransferTaskItem,
  type MaterialOption,
  type TrayPointOption,
  testBatchTransferCycle,
} from '../api/agv'
import { getErrorMessage } from '../api/http'

const dialogWidth = 'min(820px, 92vw)'
const MAX_TASK_COUNT = 4

const props = defineProps<{
  visible: boolean
  trayOptions: TrayPointOption[]
  materials: MaterialOption[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  started: [jobId: string, title: string]
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const cycleCount = ref(1)
const taskCount = ref(1)
const tasks = ref<BatchTransferTaskItem[]>([createEmptyTask()])
const submitting = ref(false)

function createEmptyTask(): BatchTransferTaskItem {
  return { source_tray: '', target_tray: '', material_type: '' }
}

function resyncTasks(target: number) {
  // 任务数量变化时按需扩容/缩容, 已有项保留以减少用户重填
  const current = tasks.value.length
  if (target > current) {
    for (let i = 0; i < target - current; i += 1) {
      tasks.value.push(createEmptyTask())
    }
  } else if (target < current) {
    tasks.value.splice(target)
  }
}

watch(taskCount, (value) => {
  resyncTasks(value)
})

watch(
  () => props.visible,
  (v) => {
    // 弹窗每次打开都重置全部参数, 避免残留
    if (v === true) {
      cycleCount.value = 1
      taskCount.value = 1
      tasks.value = [createEmptyTask()]
      submitting.value = false
    }
  },
)

const allTasksFilled = computed(() =>
  tasks.value.every(
    (task) =>
      task.source_tray !== ''
      && task.target_tray !== ''
      && task.material_type !== ''
      && task.source_tray !== task.target_tray,
  ),
)

const submitDisabled = computed(
  () => allTasksFilled.value === false || cycleCount.value < 1,
)

async function handleSubmit() {
  if (submitDisabled.value === true) {
    ElMessage.warning('请检查每个任务的源/目标点位与物料类型, 源与目标不能相同')
    return
  }
  submitting.value = true
  try {
    const payload = {
      cycle_count: cycleCount.value,
      transfer_tasks: tasks.value.map((task) => ({
        source_tray: task.source_tray,
        target_tray: task.target_tray,
        material_type: task.material_type,
      })),
    }
    const data = await testBatchTransferCycle(payload)
    emit('started', data.job_id, '批量物料转运循环测试')
    ElMessage.success('循环测试已开始, 请关注下方任务输出')
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
    title="批量物料转运循环测试"
    :width="dialogWidth"
    top="6vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    destroy-on-close
  >
    <p class="muted">
      执行 正向转运 → 充电过渡点 PP5 → 反向转运 → 充电过渡点 PP5 的循环, 一次最多 {{ MAX_TASK_COUNT }} 个任务.
    </p>
    <el-form size="small" label-width="100px">
      <el-form-item label="循环次数">
        <el-input-number v-model="cycleCount" :min="1" :max="9999" controls-position="right" />
      </el-form-item>
      <el-form-item label="任务数量">
        <el-radio-group v-model="taskCount">
          <el-radio-button v-for="n in MAX_TASK_COUNT" :key="n" :label="n">{{ n }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <div class="task-list">
      <div v-for="(task, idx) in tasks" :key="idx" class="task-row">
        <div class="task-title">任务 {{ idx + 1 }}</div>
        <div class="task-fields">
          <el-select
            v-model="task.source_tray"
            placeholder="源托盘"
            filterable
            class="task-select"
          >
            <el-option
              v-for="opt in props.trayOptions"
              :key="opt.name"
              :label="opt.label"
              :value="opt.name"
            />
          </el-select>
          <span class="arrow">&lt;-&gt;</span>
          <el-select
            v-model="task.target_tray"
            placeholder="目标托盘"
            filterable
            class="task-select"
          >
            <el-option
              v-for="opt in props.trayOptions"
              :key="opt.name"
              :label="opt.label"
              :value="opt.name"
            />
          </el-select>
          <el-select
            v-model="task.material_type"
            placeholder="物料类型"
            filterable
            class="task-select"
          >
            <el-option
              v-for="mat in props.materials"
              :key="mat.name"
              :label="`${mat.name}${mat.description ? ` - ${mat.description}` : ''}`"
              :value="mat.name"
            />
          </el-select>
        </div>
      </div>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      title="此操作将控制 AGV 在工站与充电过渡点 PP5 之间往返执行多轮循环测试, 请确保周围安全."
      show-icon
      style="margin-top: 12px"
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
  margin: 0 0 12px 0;
}
.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.task-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.task-title {
  flex: 0 0 64px;
  font-weight: 500;
}
.task-fields {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-select {
  flex: 1;
  min-width: 0;
}
.arrow {
  color: var(--el-text-color-secondary);
  font-family: monospace;
}

@media (max-width: 767.98px) {
  /* 任务字段在窄屏改纵向叠放, 箭头改文字 */
  .task-fields {
    flex-direction: column;
    align-items: stretch;
  }
  .arrow {
    text-align: center;
  }
  .arrow::before {
    content: "↓ ";
  }
}
</style>
