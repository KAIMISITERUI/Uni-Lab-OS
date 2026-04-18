<script setup lang="ts">
import { ref, watch } from 'vue'
import type { UploadRawFile } from 'element-plus'
import { ElMessage } from 'element-plus'
import { importChemicals, type ImportResponse } from '../api/chemicals'

interface Props {
  modelValue: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'imported'): void
}>()

// 选中的待上传文件与预览开关
const selectedFile = ref<File | null>(null)
const dryRun = ref(false)
const submitting = ref(false)
// 最近一次导入统计, 用于对话框内展示结果
const lastResult = ref<ImportResponse | null>(null)

// 打开对话框时重置全部状态, 避免上一轮残留
watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      selectedFile.value = null
      dryRun.value = false
      lastResult.value = null
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

// 交给 el-upload 的 http-request, 返回 false 阻止其默认上传, 实际提交在 submit 中触发
function onFileChange(raw: UploadRawFile): boolean {
  const suffix = raw.name.toLowerCase().slice(raw.name.lastIndexOf('.'))
  if (suffix !== '.xlsx' && suffix !== '.csv') {
    ElMessage.warning('仅支持 .xlsx 或 .csv 文件')
    return false
  }
  selectedFile.value = raw as unknown as File
  lastResult.value = null
  return false
}

function onFileRemove() {
  selectedFile.value = null
  lastResult.value = null
}

async function submit() {
  if (selectedFile.value === null) {
    ElMessage.warning('请先选择要导入的文件')
    return
  }
  submitting.value = true
  try {
    const resp = await importChemicals(selectedFile.value, dryRun.value)
    lastResult.value = resp
    const tip = dryRun.value ? '预览完成' : '导入完成'
    ElMessage.success(
      `${tip}: 成功 ${resp.migrated}, 跳过 ${resp.skipped}, 失败 ${resp.failed}`,
    )
    if (!dryRun.value && resp.migrated > 0) {
      emit('imported')
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '导入失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="从 xlsx / csv 添加化学品到化学品库"
    width="520px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @close="close"
  >
    <el-form label-width="110px" :model="{}">
      <el-form-item label="源文件">
        <el-upload
          :auto-upload="false"
          :multiple="false"
          :limit="1"
          accept=".xlsx,.csv"
          :before-upload="onFileChange"
          :on-remove="onFileRemove"
        >
          <el-button type="primary">选择 xlsx / csv 文件</el-button>
          <template #tip>
            <div style="color: #888; font-size: 12px; margin-top: 4px">
              仅支持 .xlsx 或 .csv, 文件内表头需与化学品库字段一致
            </div>
          </template>
        </el-upload>
      </el-form-item>
      <el-form-item label="仅预览">
        <el-checkbox v-model="dryRun">勾选后仅统计, 不写入数据库</el-checkbox>
      </el-form-item>
      <el-form-item v-if="lastResult" label="上次结果">
        <div>
          成功导入:
          <el-tag type="success">{{ lastResult.migrated }}</el-tag>
          跳过(重复或无标识):
          <el-tag type="warning" style="margin-left: 8px">{{ lastResult.skipped }}</el-tag>
          失败:
          <el-tag type="danger" style="margin-left: 8px">{{ lastResult.failed }}</el-tag>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ dryRun ? '预览' : '导入' }}
      </el-button>
    </template>
  </el-dialog>
</template>
