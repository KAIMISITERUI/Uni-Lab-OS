<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type ChemicalRow,
  deleteChemical,
  exportCsvUrl,
  exportXlsxUrl,
  listChemicals,
} from '../api/chemicals'
import ChemicalEditDialog from '../components/ChemicalEditDialog.vue'
import ChemicalDetailDialog from '../components/ChemicalDetailDialog.vue'
import ImportDialog from '../components/ImportDialog.vue'
import IntegrityPanel from '../components/IntegrityPanel.vue'
import StructurePreview from '../components/StructurePreview.vue'

const loading = ref(false)
const total = ref(0)
const rows = ref<ChemicalRow[]>([])
const activeTab = ref('chemical-list')

const query = reactive<{
  q: string
  query_type: 'cas' | 'name' | 'smiles'
  page: number
  page_size: number
}>({
  q: '',
  query_type: 'name',
  page: 1,
  page_size: 20,
})

const editDialog = reactive<{
  visible: boolean
  mode: 'create' | 'edit'
  row: ChemicalRow | null
}>({ visible: false, mode: 'create', row: null })

// 详情弹窗状态, 单独于编辑弹窗, 支持从详情点击进入编辑
const detailDialog = reactive<{
  visible: boolean
  row: ChemicalRow | null
}>({ visible: false, row: null })

const importDialogVisible = ref(false)

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: query.page,
      page_size: query.page_size,
    }
    if (query.q.trim() !== '') {
      params.q = query.q.trim()
      params.query_type = query.query_type
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
  query.page = 1
  load()
}

function openCreate() {
  editDialog.mode = 'create'
  editDialog.row = null
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

function downloadCsv() {
  // 直接通过浏览器导航触发下载, 让浏览器处理 Content-Disposition 文件名
  window.location.href = exportCsvUrl()
}

function downloadXlsx() {
  // 与 CSV 导出一致, 使用浏览器导航触发下载
  window.location.href = exportXlsxUrl()
}

onMounted(load)
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
                placeholder="按 CAS / 名称 / SMILES 搜索"
                style="width: 280px"
                clearable
                @keyup.enter="onSearch"
              />
              <el-select v-model="query.query_type" style="width: 120px">
                <el-option label="名称" value="name" />
                <el-option label="CAS" value="cas" />
                <el-option label="SMILES" value="smiles" />
              </el-select>
              <el-button type="primary" @click="onSearch">搜索</el-button>
              <el-button @click="query.q = ''; onSearch()">重置</el-button>
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
                <StructurePreview :smiles="row.smiles" :width="120" :height="90" />
              </template>
            </el-table-column>
            <el-table-column prop="substance" label="中文名" min-width="140" sortable align="center" header-align="center" />
            <el-table-column prop="substance_english_name" label="英文名" min-width="160" align="center" header-align="center" />
            <el-table-column prop="cas_number" label="CAS" width="120" align="center" header-align="center" />
            <el-table-column prop="storage_location" label="储位" width="110" align="center" header-align="center" />
            <el-table-column prop="physical_state" label="物态" width="80" align="center" header-align="center" />
            <el-table-column prop="physical_form" label="形态" width="100" align="center" header-align="center" />
            <el-table-column prop="density" label="density (g/mL)" width="120" align="center" header-align="center" />
            <el-table-column prop="molecular_weight" label="MW" width="100" align="center" header-align="center" />
            <el-table-column prop="brand" label="品牌" width="120" align="center" header-align="center" />
            <el-table-column prop="package_size" label="规格" width="100" align="center" header-align="center" />
            <el-table-column label="操作" fixed="right" width="180" align="center" header-align="center">
              <template #default="{ row }">
                <el-button size="small" type="info" link @click="openDetail(row)">详情</el-button>
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
</style>
