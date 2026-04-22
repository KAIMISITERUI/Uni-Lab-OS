<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CircleCheck, CircleClose, Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchJob, type JobState } from '../api/synthesis'
import { getErrorMessage } from '../api/http'

const props = defineProps<{
  jobId: string
}>()

const emit = defineEmits<{
  finished: [job: JobState]
}>()

const job = ref<JobState | null>(null)
const loading = ref(false)
let timer: number | undefined

const statusText = computed(() => {
  if (job.value === null) {
    return '未开始'
  }
  const map: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
  }
  return map[job.value.status] || job.value.status
})

const statusType = computed(() => {
  if (job.value === null) {
    return 'info'
  }
  if (job.value.status === 'succeeded') {
    return 'success'
  }
  if (job.value.status === 'failed') {
    return 'danger'
  }
  return 'warning'
})

async function loadJob() {
  if (props.jobId === '') {
    return
  }
  loading.value = true
  try {
    const data = await fetchJob(props.jobId)
    job.value = data
    if (data.status === 'succeeded' || data.status === 'failed') {
      stopPolling()
      emit('finished', data)
    }
  } catch (error) {
    stopPolling()
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  loadJob()
  timer = window.setInterval(loadJob, 1200)
}

function stopPolling() {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => props.jobId,
  () => {
    if (props.jobId !== '') {
      startPolling()
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="panel">
    <div class="panel-title">
      <h3>后台任务</h3>
      <div class="button-row">
        <el-tag :type="statusType">{{ statusText }}</el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="loadJob">刷新</el-button>
      </div>
    </div>

    <div v-if="job === null" class="muted">暂无后台任务</div>
    <template v-else>
      <div class="button-row" style="margin-bottom: 12px">
        <el-tag effect="plain">{{ job.name }}</el-tag>
        <el-tag v-if="job.status === 'running'" type="warning">
          <el-icon><Loading /></el-icon>
          运行中
        </el-tag>
        <el-tag v-if="job.status === 'succeeded'" type="success">
          <el-icon><CircleCheck /></el-icon>
          成功
        </el-tag>
        <el-tag v-if="job.status === 'failed'" type="danger">
          <el-icon><CircleClose /></el-icon>
          失败
        </el-tag>
      </div>

      <div class="job-log">
        <span v-for="line in job.logs" :key="line">{{ line }}</span>
      </div>

      <el-alert
        v-if="job.error"
        style="margin-top: 12px"
        type="error"
        :title="job.error"
        :closable="false"
      />
    </template>
  </div>
</template>

