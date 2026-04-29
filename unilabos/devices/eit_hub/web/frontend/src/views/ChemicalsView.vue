<script setup lang="ts">
import { onActivated, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import {
  type ChemicalRow,
  type StructureSearchRequest,
  type StructureSearchResponse,
  deleteChemical,
  exportCsvUrl,
  exportXlsxUrl,
  listChemicals,
  searchChemicalsByStructure,
} from '../api/chemicals'
import ChemicalEditDialog from '../components/ChemicalEditDialog.vue'
import ChemicalDetailDialog from '../components/ChemicalDetailDialog.vue'
import HazardDisplay from '../components/HazardDisplay.vue'
import ImportDialog from '../components/ImportDialog.vue'
import IntegrityPanel from '../components/IntegrityPanel.vue'
import StructurePreview from '../components/StructurePreview.vue'
import StructureSearchDialog from '../components/StructureSearchDialog.vue'

type StoredStructureSearch = Omit<StructureSearchRequest, 'page' | 'page_size'>

const loading = ref(false)
const total = ref(0)
const rows = ref<ChemicalRow[]>([])
const activeTab = ref('chemical-list')

const query = reactive<{
  q: string
  page: number
  page_size: number
}>({
  q: '',
  page: 1,
  page_size: 20,
})

const editDialog = reactive<{
  visible: boolean
  mode: 'create' | 'edit'
  row: Partial<ChemicalRow> | null
}>({ visible: false, mode: 'create', row: null })

// 详情弹窗状态, 单独于编辑弹窗, 支持从详情点击进入编辑
const detailDialog = reactive<{
  visible: boolean
  row: ChemicalRow | null
}>({ visible: false, row: null })

const importDialogVisible = ref(false)
const structureSearchDialogVisible = ref(false)
const activeStructureSearch = ref<StoredStructureSearch | null>(null)

async function load() {
  loading.value = true
  try {
    if (activeStructureSearch.value !== null) {
      const resp = await searchChemicalsByStructure({
        ...activeStructureSearch.value,
        page: query.page,
        page_size: query.page_size,
      })
      rows.value = resp.items
      total.value = resp.total
      return
    }

    const params: Record<string, unknown> = {
      page: query.page,
      page_size: query.page_size,
    }
    if (query.q.trim() !== '') {
      params.q = query.q.trim()
    }
    const resp = await listChemicals(params as Parameters<typeof listChemicals>[0])
    rows.value = resp.items
    total.value = resp.total
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || (err as Error).message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  activeStructureSearch.value = null
  query.page = 1
  load()
}

function resetSearch() {
  activeStructureSearch.value = null
  query.q = ''
  query.page = 1
  load()
}

function openCreate() {
  editDialog.mode = 'create'
  editDialog.row = null
  editDialog.visible = true
}

function openCreateWithPreset(rowData: Record<string, unknown>) {
  editDialog.mode = 'create'
  editDialog.row = { id: 0, ...rowData } as Partial<ChemicalRow>
  editDialog.visible = true
}

function openEdit(row: ChemicalRow) {
  editDialog.mode = 'edit'
  editDialog.row = row
  editDialog.visible = true
}

function openDetail(row: ChemicalRow) {
  detailDialog.row = row
  detailDialog.visible = true
}

function hasDisplayText(value: string | null | undefined): boolean {
  return (value ?? '').trim() !== ''
}

function displayText(value: string | null | undefined): string {
  const trimmedValue = (value ?? '').trim()
  if (trimmedValue !== '') {
    return trimmedValue
  }
  return '-'
}

function detailEntryLabel(row: ChemicalRow): string {
  const chineseName = displayText(row.substance)
  if (chineseName !== '-') {
    return `查看${chineseName}`
  }

  const englishName = displayText(row.substance_english_name)
  if (englishName !== '-') {
    return `查看${englishName}`
  }

  return `查看化学品${row.id}`
}

// 详情弹窗点击"编辑"时, 关闭详情并打开编辑对话框
function onDetailEdit(row: ChemicalRow) {
  openEdit(row)
}

async function onDelete(row: ChemicalRow) {
  try {
    await ElMessageBox.confirm(
      `确认删除化学品 "${row.substance ?? row.id}"? 此操作不可撤销.`,
      '确认删除',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteChemical(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (err: unknown) {
    ElMessage.error((err as Error).message || '删除失败')
  }
}

function onSaved() {
  load()
}

function onStructureSearched(
  payload: StoredStructureSearch,
  response: StructureSearchResponse,
) {
  activeStructureSearch.value = payload
  query.q = ''
  query.page = response.page
  query.page_size = response.page_size
  rows.value = response.items
  total.value = response.total
}

function downloadCsv() {
  // 直接通过浏览器导航触发下载, 让浏览器处理 Content-Disposition 文件名
  window.location.href = exportCsvUrl()
}

function downloadXlsx() {
  // 与 CSV 导出一致, 使用浏览器导航触发下载
  window.location.href = exportXlsxUrl()
}

onActivated(load)
</script>

<template>
  <div class="chemicals-view">
    <el-tabs v-model="activeTab" class="chemicals-tabs">
      <el-tab-pane label="化学品列表" name="chemical-list">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
              <el-input
                v-model="query.q"
                placeholder="按表格字段模糊搜索"
                style="width: 280px"
                clearable
                @keyup.enter="onSearch"
              />
              <el-button type="primary" @click="onSearch">搜索</el-button>
              <el-button @click="resetSearch">重置</el-button>
              <el-button :icon="Search" @click="structureSearchDialogVisible = true">结构式搜索</el-button>
              <div style="flex: 1" />
              <el-button type="success" @click="openCreate">新增</el-button>
              <el-button @click="importDialogVisible = true">从文件导入</el-button>
              <el-button @click="downloadCsv">导出 CSV</el-button>
              <el-button @click="downloadXlsx">导出 XLSX</el-button>
            </div>
          </template>

          <el-table v-loading="loading" :data="rows" border stripe size="small">
            <el-table-column prop="id" label="ID" width="70" sortable align="center" header-align="center" />
            <el-table-column label="结构式" width="140" align="center" header-align="center">
              <template #default="{ row }">
                <button
                  type="button"
                  class="structure-detail-entry"
                  :aria-label="detailEntryLabel(row)"
                  @click="openDetail(row)"
                >
                  <StructurePreview :smiles="row.smiles" :width="120" :height="90" />
                </button>
              </template>
            </el-table-column>
            <el-table-column prop="substance" label="中文名" min-width="140" sortable align="center" header-align="center">
              <template #default="{ row }">
                <button
                  v-if="hasDisplayText(row.substance)"
                  type="button"
                  class="name-detail-entry"
                  :aria-label="detailEntryLabel(row)"
                  @click="openDetail(row)"
                >
                  {{ displayText(row.substance) }}
                </button>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="substance_english_name" label="英文名" min-width="160" align="center" header-align="center">
              <template #default="{ row }">
                <button
                  v-if="hasDisplayText(row.substance_english_name)"
                  type="button"
                  class="name-detail-entry"
                  :aria-label="detailEntryLabel(row)"
                  @click="openDetail(row)"
                >
                  {{ displayText(row.substance_english_name) }}
                </button>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="cas_number" label="CAS" width="120" align="center" header-align="center" />
            <el-table-column label="危害" width="100" align="center" header-align="center">
              <template #default="{ row }">
                <HazardDisplay :chemical="row" mode="summary" summary-part="level" />
              </template>
            </el-table-column>
            <el-table-column label="具体内容" width="260" align="center" header-align="center">
              <template #default="{ row }">
                <HazardDisplay :chemical="row" mode="summary" summary-part="content" />
              </template>
            </el-table-column>
            <el-table-column prop="storage_location" label="储位" width="110" align="center" header-align="center" />
            <el-table-column prop="physical_state" label="物态" width="80" align="center" header-align="center" />
            <el-table-column prop="physical_form" label="形态" width="100" align="center" header-align="center" />
            <el-table-column prop="density" label="density (g/mL)" width="120" align="center" header-align="center" />
            <el-table-column prop="molecular_weight" label="MW" width="100" align="center" header-align="center" />
            <el-table-column prop="brand" label="品牌" width="120" align="center" header-align="center" />
            <el-table-column prop="package_size" label="规格" width="100" align="center" header-align="center" />
            <el-table-column label="操作" fixed="right" width="120" align="center" header-align="center">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" link @click="onDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            style="margin-top: 16px; justify-content: flex-end; display: flex"
            v-model:current-page="query.page"
            v-model:page-size="query.page_size"
            :total="total"
            :page-sizes="[20, 50, 100, 200]"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="load"
            @size-change="load"
          />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="完整性维护" name="integrity-maintenance" lazy>
        <IntegrityPanel />
      </el-tab-pane>
    </el-tabs>

    <ChemicalEditDialog
      v-model="editDialog.visible"
      :mode="editDialog.mode"
      :row="editDialog.row"
      @saved="onSaved"
    />
    <StructureSearchDialog
      v-model="structureSearchDialogVisible"
      :page-size="query.page_size"
      @searched="onStructureSearched"
      @online-preview="openCreateWithPreset"
    />
    <ChemicalDetailDialog
      v-model="detailDialog.visible"
      :chemical="detailDialog.row"
      @edit="onDetailEdit"
    />
    <ImportDialog v-model="importDialogVisible" @imported="load" />
  </div>
</template>

<style scoped>
.chemicals-view {
  padding: 0;
}

.chemicals-tabs {
  min-width: 0;
}

.structure-detail-entry,
.name-detail-entry {
  border: 0;
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.structure-detail-entry {
  display: inline-flex;
  padding: 0;
  line-height: 0;
  border-radius: 4px;
}

.structure-detail-entry :deep(.structure-preview) {
  transition: border-color 0.2s, box-shadow 0.2s;
}

.structure-detail-entry:hover :deep(.structure-preview),
.structure-detail-entry:focus-visible :deep(.structure-preview) {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}

.name-detail-entry {
  max-width: 100%;
  padding: 0;
  color: inherit;
  line-height: 1.4;
  text-align: center;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.name-detail-entry:hover {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.structure-detail-entry:focus-visible,
.name-detail-entry:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
</style>
