<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  type ChemicalRow,
  type DuplicateNameGroup,
  type IntegrityReport,
  fetchIntegrity,
} from '../api/chemicals'
import ChemicalEditDialog from './ChemicalEditDialog.vue'

const report = ref<IntegrityReport | null>(null)
const loading = ref(false)

// 编辑对话框状态; 与 ChemicalsView.vue 中的 openEdit 模式保持一致
const editDialog = reactive<{
  visible: boolean
  row: ChemicalRow | null
}>({ visible: false, row: null })

// 默认展开全部区块, 让用户一眼看到全部问题
const activeSections = ref<string[]>([
  'duplicate_chinese_names',
  'duplicate_english_names',
  'missing_physical_state',
  'missing_physical_form',
  'neat_missing_molecular_weight',
  'neat_liquid_missing_density',
  'beads_solution_missing_content',
])

async function refresh() {
  loading.value = true
  try {
    report.value = await fetchIntegrity()
  } catch (err: unknown) {
    ElMessage.error((err as Error).message || '获取完整性检查结果失败')
  } finally {
    loading.value = false
  }
}

function openEdit(row: ChemicalRow) {
  editDialog.row = row
  editDialog.visible = true
}

function onSaved() {
  // 编辑保存后重新拉取完整性结果, 已修复的问题应自动从清单中消失
  refresh()
}

// 把 DuplicateNameGroup[] 平铺成扁平行, 每行附 group_name 与同组高亮 class
interface FlatDuplicateRow extends ChemicalRow {
  __group_name: string
  __group_index: number
}

function flattenGroups(groups: DuplicateNameGroup[]): FlatDuplicateRow[] {
  const flat: FlatDuplicateRow[] = []
  groups.forEach((group, idx) => {
    group.rows.forEach((row) => {
      flat.push({ ...row, __group_name: group.name, __group_index: idx })
    })
  })
  return flat
}

const duplicateChineseRows = computed<FlatDuplicateRow[]>(() =>
  report.value ? flattenGroups(report.value.duplicate_chinese_names) : [],
)
const duplicateEnglishRows = computed<FlatDuplicateRow[]>(() =>
  report.value ? flattenGroups(report.value.duplicate_english_names) : [],
)

// 同组行使用奇偶交替的浅色背景做视觉分组
function dupRowClassName({ row }: { row: FlatDuplicateRow }): string {
  return row.__group_index % 2 === 0 ? 'dup-group-a' : 'dup-group-b'
}

const totalIssues = computed(() => {
  if (!report.value) return 0
  const r = report.value
  return (
    duplicateChineseRows.value.length +
    duplicateEnglishRows.value.length +
    r.missing_physical_state.length +
    r.missing_physical_form.length +
    r.neat_missing_molecular_weight.length +
    r.neat_liquid_missing_density.length +
    r.beads_solution_missing_content.length
  )
})

onMounted(refresh)
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-weight: 600">完整性检查</span>
        <el-button size="small" @click="refresh">刷新</el-button>
        <div style="flex: 1" />
        <el-tag v-if="report" :type="totalIssues === 0 ? 'success' : 'warning'">
          共 {{ totalIssues }} 项问题
        </el-tag>
      </div>
    </template>

    <div v-if="report && totalIssues === 0" style="color: #67c23a; padding: 16px 0">
      未发现问题, 化学品库完整性良好.
    </div>

    <el-collapse v-if="report && totalIssues > 0" v-model="activeSections">
      <!-- 1. 中文名重复 -->
      <el-collapse-item
        v-if="duplicateChineseRows.length > 0"
        name="duplicate_chinese_names"
      >
        <template #title>
          <span style="font-weight: 600">
            中文名重复
            <el-tag size="small" type="danger" style="margin-left: 8px">
              {{ report.duplicate_chinese_names.length }} 组 / {{ duplicateChineseRows.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 同名条目应合并为同一记录, 或修改名称以区分.
        </div>
        <el-table
          :data="duplicateChineseRows"
          :row-class-name="dupRowClassName"
          border
          size="small"
        >
          <el-table-column prop="__group_name" label="重复中文名" min-width="160" />
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_form" label="形态" width="90" />
          <el-table-column prop="physical_state" label="物态" width="80" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 2. 英文名重复 -->
      <el-collapse-item
        v-if="duplicateEnglishRows.length > 0"
        name="duplicate_english_names"
      >
        <template #title>
          <span style="font-weight: 600">
            英文名重复
            <el-tag size="small" type="danger" style="margin-left: 8px">
              {{ report.duplicate_english_names.length }} 组 / {{ duplicateEnglishRows.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 同名条目应合并为同一记录, 或修改名称以区分.
        </div>
        <el-table
          :data="duplicateEnglishRows"
          :row-class-name="dupRowClassName"
          border
          size="small"
        >
          <el-table-column prop="__group_name" label="重复英文名" min-width="180" />
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_form" label="形态" width="90" />
          <el-table-column prop="physical_state" label="物态" width="80" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 3. 物态缺失 -->
      <el-collapse-item
        v-if="report.missing_physical_state.length > 0"
        name="missing_physical_state"
      >
        <template #title>
          <span style="font-weight: 600">
            物态 (physical_state) 缺失
            <el-tag size="small" type="warning" style="margin-left: 8px">
              {{ report.missing_physical_state.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 补全 physical_state, 取值 liquid / solid / gas.
        </div>
        <el-table :data="report.missing_physical_state" border size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_form" label="形态" width="90" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 4. 形态缺失 -->
      <el-collapse-item
        v-if="report.missing_physical_form.length > 0"
        name="missing_physical_form"
      >
        <template #title>
          <span style="font-weight: 600">
            形态 (physical_form) 缺失
            <el-tag size="small" type="warning" style="margin-left: 8px">
              {{ report.missing_physical_form.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 补全 physical_form, 取值 neat / solution / beads.
        </div>
        <el-table :data="report.missing_physical_form" border size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_state" label="物态" width="80" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 5. neat 缺分子量 -->
      <el-collapse-item
        v-if="report.neat_missing_molecular_weight.length > 0"
        name="neat_missing_molecular_weight"
      >
        <template #title>
          <span style="font-weight: 600">
            neat 物质缺分子量
            <el-tag size="small" type="warning" style="margin-left: 8px">
              {{ report.neat_missing_molecular_weight.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 形态为 neat 的物质应填写 molecular_weight (g/mol).
        </div>
        <el-table :data="report.neat_missing_molecular_weight" border size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_state" label="物态" width="80" />
          <el-table-column prop="molecular_weight" label="MW" width="90" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 6. neat liquid 缺密度 -->
      <el-collapse-item
        v-if="report.neat_liquid_missing_density.length > 0"
        name="neat_liquid_missing_density"
      >
        <template #title>
          <span style="font-weight: 600">
            neat 液体缺密度
            <el-tag size="small" type="warning" style="margin-left: 8px">
              {{ report.neat_liquid_missing_density.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 形态为 neat 且物态为 liquid 的物质应填写 density (g/mL).
        </div>
        <el-table :data="report.neat_liquid_missing_density" border size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="density" label="density" width="100" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>

      <!-- 7. beads / solution 缺含量 -->
      <el-collapse-item
        v-if="report.beads_solution_missing_content.length > 0"
        name="beads_solution_missing_content"
      >
        <template #title>
          <span style="font-weight: 600">
            beads / solution 缺含量
            <el-tag size="small" type="warning" style="margin-left: 8px">
              {{ report.beads_solution_missing_content.length }} 行
            </el-tag>
          </span>
        </template>
        <div style="color: #909399; margin-bottom: 8px">
          建议: 形态为 beads 或 solution 的物质应填写 active_content (solution: mol/L; beads: wt%).
        </div>
        <el-table :data="report.beads_solution_missing_content" border size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="substance" label="中文名" min-width="140" />
          <el-table-column prop="substance_english_name" label="英文名" min-width="160" />
          <el-table-column prop="cas_number" label="CAS" width="120" />
          <el-table-column prop="physical_form" label="形态" width="90" />
          <el-table-column prop="active_content" label="active_content" width="140" />
          <el-table-column label="操作" fixed="right" width="80">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEdit(row)">
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <ChemicalEditDialog
      v-model="editDialog.visible"
      mode="edit"
      :row="editDialog.row"
      @saved="onSaved"
    />
  </el-card>
</template>

<style scoped>
:deep(.dup-group-a) {
  background-color: #fafcff;
}
:deep(.dup-group-b) {
  background-color: #f4f9ff;
}
</style>
