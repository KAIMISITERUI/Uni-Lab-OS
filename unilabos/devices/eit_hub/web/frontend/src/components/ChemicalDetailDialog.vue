<script setup lang="ts">
import type { ChemicalRow } from '../api/chemicals'
import StructurePreview from './StructurePreview.vue'

/**
 * 功能:
 *     化学品详情弹窗, 左侧展示大尺寸 2D 结构图, 右侧展示字段清单
 * 参数:
 *     modelValue 弹窗显示状态, 遵循 v-model 约定
 *     chemical 当前展示的化学品行数据, null 时不渲染正文
 *     showEdit 是否展示编辑入口, 默认展示
 * 事件:
 *     update:modelValue 关闭弹窗
 *     edit 请求切换到编辑模式(由列表视图接管)
 */
interface Props {
  modelValue: boolean
  chemical: ChemicalRow | null
  showEdit?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showEdit: true,
})
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'edit', row: ChemicalRow): void
}>()

function close(): void {
  emit('update:modelValue', false)
}

function onEdit(): void {
  if (props.chemical !== null) {
    emit('edit', props.chemical)
    // 触发编辑后关闭详情弹窗, 由外层打开编辑对话框
    close()
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="chemical ? `化学品详情: ${chemical.substance ?? ''}` : '化学品详情'"
    width="920px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @close="close"
  >
    <div v-if="chemical" class="detail-body">
      <div class="detail-left">
        <StructurePreview :smiles="chemical.smiles" :width="500" :height="400" />
      </div>
      <div class="detail-right">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="ID">{{ chemical.id }}</el-descriptions-item>
          <el-descriptions-item label="中文名">
            {{ chemical.substance ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="英文名">
            {{ chemical.substance_english_name ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="CAS 号">
            {{ chemical.cas_number ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="合成工站 fid">
            {{ chemical.chemical_id ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="储位">
            {{ chemical.storage_location ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="物态">
            {{ chemical.physical_state ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="形态">
            {{ chemical.physical_form ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="密度 (g/mL)">
            {{ chemical.density ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="分子量">
            {{ chemical.molecular_weight ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="活性含量">
            {{ chemical.active_content ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="品牌">
            {{ chemical.brand ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="规格">
            {{ chemical.package_size ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="SMILES">
            <span class="smiles-raw">{{ chemical.smiles ?? '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="别名">
            {{ chemical.other_name ?? '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
    <template #footer>
      <el-button v-if="showEdit" type="primary" @click="onEdit">编辑</el-button>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.detail-body {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}
.detail-left {
  flex: 0 0 auto;
}
.detail-right {
  flex: 1;
  min-width: 0;
}
.smiles-raw {
  font-family: var(--el-font-family-mono, monospace);
  word-break: break-all;
}
</style>
