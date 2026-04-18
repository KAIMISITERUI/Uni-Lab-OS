<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { lookupChemical } from '../api/chemicals'

interface Props {
  modelValue: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'imported'): void
}>()

const submitting = ref(false)
const form = reactive<{ query: string; query_type: 'cas' | 'name' | 'smiles' }>({
  query: '',
  query_type: 'cas',
})

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      form.query = ''
      form.query_type = 'cas'
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  const q = form.query.trim()
  if (q === '') {
    ElMessage.warning('请输入查询字符串')
    return
  }
  submitting.value = true
  try {
    const resp = await lookupChemical({ query: q, query_type: form.query_type })
    if (!resp.success) {
      ElMessage.warning(resp.message || '未找到化合物')
      return
    }
    if (resp.duplicate) {
      ElMessage.info(`化合物已存在: ${resp.duplicate_substance ?? ''}`)
      emit('imported')
      close()
      return
    }
    ElMessage.success(`已入库, id=${resp.row_id}`)
    emit('imported')
    close()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '在线查询失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="在线查询并入库"
    width="500px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @close="close"
  >
    <el-form label-width="100px" :model="form">
      <el-form-item label="查询类型">
        <el-radio-group v-model="form.query_type">
          <el-radio value="cas">CAS</el-radio>
          <el-radio value="name">名称</el-radio>
          <el-radio value="smiles">SMILES</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="查询内容">
        <el-input v-model="form.query" placeholder="例: 64-17-5 / Ethanol / CCO" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">查询并入库</el-button>
    </template>
  </el-dialog>
</template>
