<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  type ChemicalRow,
  createChemical,
  updateChemical,
} from '../api/chemicals'

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

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, blankForm())
    if (props.mode === 'edit' && props.row) {
      Object.keys(form).forEach((key) => {
        ;(form as Record<string, unknown>)[key] = (props.row as Record<string, unknown>)[key] ?? ''
      })
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!form.substance || String(form.substance).trim() === '') {
    ElMessage.warning('substance (中文名) 必填')
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
    <el-form label-width="140px" :model="form">
      <el-form-item label="substance (中文名)" required>
        <el-input v-model="form.substance" placeholder="例: 乙醇" />
      </el-form-item>
      <el-form-item label="英文名">
        <el-input v-model="form.substance_english_name" placeholder="例: Ethanol" />
      </el-form-item>
      <el-form-item label="CAS 号">
        <el-input v-model="form.cas_number" placeholder="例: 64-17-5" />
      </el-form-item>
      <el-form-item label="工站 chemical_id">
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
        <el-input v-model="form.smiles" />
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
