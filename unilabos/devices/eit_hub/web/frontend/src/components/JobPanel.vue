<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { CircleCheck, CircleClose, Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchJob, type JobState } from '../api/synthesis'
import { fetchAgvJob } from '../api/agv'
import { fetchLabelPrinterJob } from '../api/labelPrinter'
import { getErrorMessage } from '../api/http'
import ResultConsole from './ResultConsole.vue'

const props = withDefaults(
  defineProps<{
    jobId: string
    title?: string
    source?: 'synthesis' | 'agv' | 'label-printer'
  }>(),
  {
    title: '运行结果',
    source: 'synthesis',
  },
)

async function dispatchFetchJob(jobId: string): Promise<JobState> {
  if (props.source === 'agv') {
    const data = await fetchAgvJob(jobId)
    return data as JobState
  }
  if (props.source === 'label-printer') {
    return fetchLabelPrinterJob(jobId)
  }
  return fetchJob(jobId)
}

const emit = defineEmits<{
  updated: [job: JobState]
  finished: [job: JobState]
}>()

const job = ref<JobState | null>(null)
const loading = ref(false)
const isActive = ref(false)
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
    stopped: '已停止',
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
  if (job.value.status === 'stopped') {
    return 'danger'
  }
  return 'warning'
})

const resultRecord = computed<Record<string, unknown> | null>(() => {
  if (job.value === null) {
    return null
  }
  const result = job.value.result
  if (result === null || result === undefined) {
    return null
  }
  if (Array.isArray(result) === true || typeof result !== 'object') {
    return null
  }
  return result as Record<string, unknown>
})

const hasResourceMissingResult = computed(() => {
  if (job.value === null || job.value.name !== '物料核算') {
    return false
  }
  if (resultRecord.value === null) {
    return false
  }
  return Array.isArray(resultRecord.value.missing)
})

const missingItems = computed(() => {
  if (hasResourceMissingResult.value === false || resultRecord.value === null) {
    return []
  }
  const missing = resultRecord.value.missing
  if (Array.isArray(missing) === false) {
    return []
  }
  return missing.map((item) => formatResultItem(item))
})

async function loadJob() {
  if (props.jobId === '') {
    return
  }
  loading.value = true
  try {
    const data = await dispatchFetchJob(props.jobId)
    job.value = data
    emit('updated', data)
    if (data.status === 'succeeded' || data.status === 'failed' || data.status === 'stopped') {
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
  if (props.jobId === '') {
    return
  }
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

function formatResultItem(item: unknown): string {
  if (typeof item === 'string') {
    return item
  }
  if (item === null || item === undefined) {
    return ''
  }
  if (typeof item === 'object') {
    return JSON.stringify(item)
  }
  return String(item)
}

watch(
  () => props.jobId,
  () => {
    job.value = null
    if (isActive.value === true && props.jobId !== '') {
      startPolling()
    }
  },
)

onActivated(() => {
  isActive.value = true
  if (props.jobId !== '') {
    startPolling()
  }
})

onMounted(() => {
  isActive.value = true
  if (props.jobId !== '') {
    startPolling()
  }
})

onDeactivated(() => {
  isActive.value = false
  stopPolling()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="panel">
    <div class="panel-title">
      <h3>{{ props.title }}</h3>
      <div class="button-row">
        <el-tag :type="statusType">{{ statusText }}</el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="loadJob">刷新</el-button>
      </div>
    </div>

    <div v-if="job === null" class="muted">暂无运行结果</div>
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
        <el-tag v-if="job.status === 'stopped'" type="danger">
          <el-icon><CircleClose /></el-icon>
          已停止
        </el-tag>
      </div>

      <div class="job-log-wrapper">
        <ResultConsole :entries="job.logs" empty-text="暂无运行结果" />
      </div>

      <el-alert
        v-if="job.error"
        style="margin-top: 12px"
        type="error"
        :title="job.error"
        :closable="false"
      />

      <el-alert
        v-if="missingItems.length > 0"
        style="margin-top: 12px"
        type="warning"
        title="资源审查缺失项"
        :closable="false"
      >
        <ul class="missing-list">
          <li v-for="item in missingItems" :key="item">{{ item }}</li>
        </ul>
      </el-alert>

      <el-alert
        v-else-if="hasResourceMissingResult === true"
        style="margin-top: 12px"
        type="success"
        title="资源审查无缺失项"
        :closable="false"
      />
    </template>
  </div>
</template>

<style scoped>
.missing-list {
  margin: 6px 0 0;
  padding-left: 18px;
  line-height: 1.6;
}
</style>
