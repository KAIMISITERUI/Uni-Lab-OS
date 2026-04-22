<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  type ChemicalRow,
  createChemical,
  lookupChemical,
  updateChemical,
} from '../api/chemicals'
import StructurePreview from './StructurePreview.vue'

interface Props {
  modelValue: boolean
  mode: 'create' | 'edit'
  row?: ChemicalRow | null
}

const props = withDefaults(defineProps<Props>(), { row: null })
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'saved', row: ChemicalRow): void
}>()

const submitting = ref(false)

// 编辑/新增公用的字段集合; 不含 id/created_at/updated_at
const blankForm = (): Partial<ChemicalRow> => ({
  substance: '',
  substance_english_name: '',
  cas_number: '',
  chemical_id: '',
  brand: '',
  package_size: '',
  storage_location: '',
  physical_state: '',
  physical_form: '',
  density: null,
  molecular_weight: null,
  active_content: '',
  smiles: '',
  other_name: '',
})

const form = reactive<Partial<ChemicalRow>>(blankForm())

// SMILES 预览使用 300ms 防抖, 避免输入过程中每次按键都调用 RDKit 渲染
const previewSmiles = ref<string>('')
let previewTimer: ReturnType<typeof setTimeout> | null = null

function schedulePreviewUpdate(val: string | null | undefined): void {
  if (previewTimer !== null) {
    clearTimeout(previewTimer)
  }
  previewTimer = setTimeout(() => {
    previewSmiles.value = (val ?? '').toString()
    previewTimer = null
  }, 300)
}

watch(
  () => form.smiles,
  (val) => {
    schedulePreviewUpdate(val as string | null | undefined)
  },
)

onBeforeUnmount(() => {
  if (previewTimer !== null) {
    clearTimeout(previewTimer)
  }
})

// 新增模式下的在线查询状态
const lookupState = reactive<{
  queryType: 'cas' | 'name' | 'smiles'
  queryText: string
  loading: boolean
}>({
  queryType: 'cas',
  queryText: '',
  loading: false,
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, blankForm())
    // 打开对话框时重置查询栏, 避免上次内容残留
    lookupState.queryType = 'cas'
    lookupState.queryText = ''
    lookupState.loading = false
    if (props.mode === 'edit' && props.row) {
      Object.keys(form).forEach((key) => {
        ;(form as Record<string, unknown>)[key] = (props.row as Record<string, unknown>)[key] ?? ''
      })
    }
    // 对话框重新打开时立即刷新预览, 避免沿用上一次弹窗的旧值
    if (previewTimer !== null) {
      clearTimeout(previewTimer)
      previewTimer = null
    }
    previewSmiles.value = (form.smiles ?? '').toString()
  },
)

function close() {
  emit('update:modelValue', false)
}

// 数值字段转换: 空值/NaN 统一为 null, 与 blankForm 保持一致
function toNumberOrNull(val: unknown): number | null {
  if (val === null || val === undefined || val === '') return null
  const num = Number(val)
  return Number.isFinite(num) ? num : null
}

async function onLookup() {
  const q = lookupState.queryText.trim()
  if (q === '') {
    ElMessage.warning('请输入查询字符串')
    return
  }
  lookupState.loading = true
  try {
    const resp = await lookupChemical({ query: q, query_type: lookupState.queryType })
    if (!resp.success || !resp.row_data) {
      ElMessage.warning(resp.message || '未找到化合物')
      return
    }
    // 仅保留 form 已声明的字段, 避免 row_data 中的额外键污染保存 payload
    const allowed = Object.keys(blankForm())
    const numericKeys = new Set(['density', 'molecular_weight'])
    allowed.forEach((key) => {
      if (!(key in resp.row_data!)) return
      const value = (resp.row_data as Record<string, unknown>)[key]
      if (numericKeys.has(key)) {
        ;(form as Record<string, unknown>)[key] = toNumberOrNull(value)
      } else {
        ;(form as Record<string, unknown>)[key] = value ?? ''
      }
    })
    ElMessage.success('已填充查询结果, 请检查后保存')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '在线查询失败')
  } finally {
    lookupState.loading = false
  }
}

async function submit() {
  if (!form.substance || String(form.substance).trim() === '') {
    ElMessage.warning('中文名必填')
    return
  }
  // 收集非空字段, 避免把空字符串写入数据库
  const payload: Record<string, unknown> = {}
  Object.entries(form).forEach(([key, val]) => {
    if (val === '' || val === null || val === undefined) return
    payload[key] = val
  })

  submitting.value = true
  try {
    let saved: ChemicalRow
    if (props.mode === 'create') {
      saved = await createChemical(payload as Partial<ChemicalRow>)
      ElMessage.success(`已新增: ${saved.substance}`)
    } else {
      if (!props.row) throw new Error('编辑模式缺少 row')
      saved = await updateChemical(props.row.id, payload as Partial<ChemicalRow>)
      ElMessage.success(`已保存: ${saved.substance}`)
    }
    emit('saved', saved)
    close()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '保存失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="mode === 'create' ? '新增化学品' : `编辑: ${row?.substance ?? ''}`"
    width="640px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @close="close"
  >
    <!-- 新增模式的在线查询栏: 查询结果直接填入下方表单, 用户检查后再保存 -->
    <div v-if="mode === 'create'" class="lookup-bar">
      <el-radio-group v-model="lookupState.queryType" size="small">
        <el-radio value="cas">CAS</el-radio>
        <el-radio value="name">名称</el-radio>
        <el-radio value="smiles">SMILES</el-radio>
      </el-radio-group>
      <el-input
        v-model="lookupState.queryText"
        placeholder="例: 64-17-5 / Ethanol / CCO"
        style="flex: 1"
        @keyup.enter="onLookup"
      />
      <el-button type="primary" :loading="lookupState.loading" @click="onLookup">
        在线查询
      </el-button>
    </div>

    <el-form label-width="140px" :model="form">
      <el-form-item label="中文名" required>
        <el-input v-model="form.substance" placeholder="例: 乙醇" />
      </el-form-item>
      <el-form-item label="英文名">
        <el-input v-model="form.substance_english_name" placeholder="例: Ethanol" />
      </el-form-item>
      <el-form-item label="CAS 号">
        <el-input v-model="form.cas_number" placeholder="例: 64-17-5" />
      </el-form-item>
      <el-form-item label="合成工站 fid">
        <el-input v-model="form.chemical_id" placeholder="对齐工站后回写" />
      </el-form-item>
      <el-form-item label="storage_location">
        <el-input v-model="form.storage_location" placeholder="输入存储位置" />
      </el-form-item>
      <el-form-item label="physical_state">
        <el-select v-model="form.physical_state" clearable placeholder="物态">
          <el-option label="liquid" value="liquid" />
          <el-option label="solid" value="solid" />
          <el-option label="gas" value="gas" />
        </el-select>
      </el-form-item>
      <el-form-item label="physical_form">
        <el-select v-model="form.physical_form" clearable placeholder="形态">
          <el-option label="neat" value="neat" />
          <el-option label="solution" value="solution" />
          <el-option label="beads" value="beads" />
        </el-select>
      </el-form-item>
      <el-form-item label="density (g/mL)">
        <el-input-number v-model="form.density" :precision="4" :step="0.01" :min="0" :controls="false" />
      </el-form-item>
      <el-form-item label="molecular_weight">
        <el-input-number v-model="form.molecular_weight" :precision="4" :step="0.01" :min="0" :controls="false" />
      </el-form-item>
      <el-form-item label="active_content">
        <el-input v-model="form.active_content" placeholder="solution: mol/L; beads: wt%" />
      </el-form-item>
      <el-form-item label="brand">
        <el-input v-model="form.brand" />
      </el-form-item>
      <el-form-item label="package_size">
        <el-input v-model="form.package_size" />
      </el-form-item>
      <el-form-item label="SMILES">
        <div class="smiles-field">
          <el-input v-model="form.smiles" placeholder="例: CCO" />
          <StructurePreview
            class="smiles-preview"
            :smiles="previewSmiles"
            :width="320"
            :height="220"
          />
        </div>
      </el-form-item>
      <el-form-item label="other_name">
        <el-input v-model="form.other_name" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.lookup-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}
.smiles-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.smiles-preview {
  align-self: flex-start;
}
</style>
