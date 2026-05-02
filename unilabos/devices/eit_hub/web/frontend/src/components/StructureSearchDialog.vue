<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as OCL from 'openchemlib'
import {
  lookupChemical,
  searchChemicalsByStructure,
  type StructureSearchMatchMode,
  type StructureSearchRequest,
  type StructureSearchResponse,
} from '../api/chemicals'

/**
 * 功能:
 *     结构式搜索弹窗. 用户在 OpenChemLib 编辑器中绘制结构后, 按完整结构或子结构搜索本地库.
 * 参数:
 *     modelValue 弹窗显示状态.
 *     pageSize 搜索结果分页大小, 与外层列表保持一致.
 * 事件:
 *     searched 返回结构搜索请求与响应, 由外层刷新表格.
 *     online-preview 完整结构本地未命中且用户确认在线搜索后, 返回预填新增表单的数据.
 */
interface Props {
  modelValue: boolean
  pageSize?: number
}

type StoredStructureSearch = Omit<StructureSearchRequest, 'page' | 'page_size'>

const props = withDefaults(defineProps<Props>(), {
  pageSize: 20,
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'searched', payload: StoredStructureSearch, response: StructureSearchResponse): void
  (e: 'online-preview', rowData: Record<string, unknown>): void
}>()

const editorHost = ref<HTMLElement | null>(null)
const matchMode = ref<StructureSearchMatchMode>('exact')
const loading = ref(false)

let editor: OCL.CanvasEditor | null = null

function applyEditorDrawingBorder(): void {
  if (editorHost.value === null) {
    return
  }

  const editorRoot = editorHost.value.querySelector<HTMLElement>(
    '[data-openchemlib-canvas-editor="true"]',
  )
  const shadowRoot = editorRoot?.shadowRoot
  if (editorRoot === null || editorRoot === undefined || shadowRoot === null || shadowRoot === undefined) {
    return
  }

  const toolbarCanvas = shadowRoot.querySelector<HTMLCanvasElement>('canvas')
  if (toolbarCanvas !== null) {
    toolbarCanvas.style.flex = '0 0 auto'
  }

  const drawingArea = shadowRoot.querySelector<HTMLElement>('div')
  if (drawingArea === null) {
    return
  }

  // OpenChemLib 的绘图区在 shadow DOM 内, 初始化后直接给右侧画布容器加边框.
  drawingArea.style.flex = '1 1 auto'
  drawingArea.style.width = 'auto'
  drawingArea.style.minWidth = '0'
  drawingArea.style.height = '100%'
  drawingArea.style.boxSizing = 'border-box'
  drawingArea.style.border = '1px solid #dcdfe6'
  drawingArea.style.borderRadius = '4px'
  drawingArea.style.overflow = 'hidden'
  drawingArea.style.backgroundColor = '#fff'
}

function close(): void {
  emit('update:modelValue', false)
}

function destroyEditor(): void {
  if (editor === null) {
    return
  }
  try {
    editor.destroy()
  } catch {
    // 编辑器销毁失败不影响弹窗关闭.
  }
  editor = null
}

async function ensureEditor(): Promise<void> {
  await nextTick()
  if (editor !== null && editor.isDestroyed === false) {
    return
  }
  if (editorHost.value === null) {
    return
  }
  editor = new OCL.CanvasEditor(editorHost.value, {
    initialMode: 'molecule',
  })
  applyEditorDrawingBorder()
}

function clearEditor(): void {
  if (editor === null || editor.isDestroyed === true) {
    return
  }
  editor.clearAll()
}

async function readEditorSmiles(): Promise<string | null> {
  await ensureEditor()
  if (editor === null || editor.isDestroyed === true) {
    ElMessage.error('结构编辑器初始化失败')
    return null
  }

  const molecule = editor.getMolecule()
  if (molecule.getAllAtoms() === 0) {
    ElMessage.warning('请先绘制结构式')
    return null
  }

  const smiles = molecule.toIsomericSmiles().trim()
  if (smiles === '') {
    ElMessage.warning('未生成有效结构式')
    return null
  }
  return smiles
}

async function askOnlineLookup(querySmiles: string): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '本地库未找到对应结构, 是否在线搜索并预填新增化学品?',
      '本地未命中',
      {
        confirmButtonText: '在线搜索',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  loading.value = true
  try {
    const response = await lookupChemical({
      query: querySmiles,
      query_type: 'smiles',
    })
    if (response.success !== true || response.row_data == null) {
      ElMessage.warning(response.message || '在线搜索未找到化合物')
      return
    }
    emit('online-preview', response.row_data)
    ElMessage.success('已填充在线结果, 请检查后保存')
    close()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '在线搜索失败')
  } finally {
    loading.value = false
  }
}

async function submitSearch(): Promise<void> {
  const smiles = await readEditorSmiles()
  if (smiles === null) {
    return
  }

  const payload: StoredStructureSearch = {
    structure: smiles,
    input_format: 'smiles',
    match_mode: matchMode.value,
  }

  loading.value = true
  try {
    const response = await searchChemicalsByStructure({
      ...payload,
      page: 1,
      page_size: props.pageSize,
    })
    emit('searched', payload, response)

    if (response.total > 0) {
      ElMessage.success(`已找到 ${response.total} 条匹配化学品`)
      close()
      return
    }

    if (matchMode.value === 'exact') {
      await askOnlineLookup(response.query_smiles)
    } else {
      ElMessage.warning('未找到包含该子结构的化学品')
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '结构式搜索失败')
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  destroyEditor()
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="结构式搜索"
    width="860px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @opened="ensureEditor"
    @closed="destroyEditor"
  >
    <div class="structure-search-dialog">
      <div class="search-toolbar">
        <el-radio-group v-model="matchMode" size="small">
          <el-radio-button value="exact">完整结构</el-radio-button>
          <el-radio-button value="substructure">子结构</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="clearEditor">清空</el-button>
      </div>
      <div ref="editorHost" class="structure-editor" />
    </div>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submitSearch">
        搜索
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.structure-search-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.structure-editor {
  width: 100%;
  height: 520px;
  min-height: 520px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
  background: #fff;
}

@media (max-width: 767.98px) {
  .structure-editor {
    height: calc(100dvh - 240px);
    min-height: 360px;
  }

  .search-toolbar {
    flex-wrap: wrap;
  }
}
</style>
