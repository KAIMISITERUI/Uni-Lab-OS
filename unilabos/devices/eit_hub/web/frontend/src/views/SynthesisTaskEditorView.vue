<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  DocumentChecked,
  Minus,
  Plus,
  Refresh,
  Upload,
} from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type JobState,
  type ReactionTemplate,
  checkResource,
  fetchReactionTemplate,
  saveReactionTemplate,
  submitReactionTemplate,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'
import EditableSpreadsheet from '../components/EditableSpreadsheet.vue'

type SpreadsheetRow = Record<string, unknown> | unknown[]

const TASK_EDITOR_DRAFT_KEY = 'eit_hub.synthesis_task_editor_draft'

const templateData = ref<ReactionTemplate | null>(null)
const currentJobId = ref('')
const loading = ref(false)
const chemicalLoading = ref(false)
let skipTemplatePersist = false

const experimentCount = computed(() => templateData.value?.rows.length || 12)

const spreadsheetColumns = computed<Array<Record<string, unknown>>>(() => {
  if (templateData.value === null) {
    return []
  }
  return templateData.value.headers.map((header, index) => {
    if (index === 0) {
      return {
        data: index,
        readOnly: true,
        width: 90,
      }
    }
    if (isReagentNameColumn(header, index) === true) {
      return {
        data: index,
        type: 'autocomplete',
        source: chemicalNameSource,
        strict: false,
        allowInvalid: true,
        trimDropdown: false,
        width: 220,
      }
    }
    return {
      data: index,
      type: 'text',
      width: 180,
    }
  })
})

const spreadsheetKey = computed(() => {
  if (templateData.value === null) {
    return 'empty'
  }
  return `${templateData.value.headers.join('|')}-${templateData.value.rows.length}`
})

async function loadTemplate(useDraft = true) {
  loading.value = true
  try {
    const remoteTemplate = await fetchReactionTemplate()
    const draftTemplate = useDraft === true ? readTemplateDraft(remoteTemplate) : null
    if (useDraft !== true) {
      clearTemplateDraft()
    }
    setTemplateData(draftTemplate || remoteTemplate)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadChemicalNames(query: string): Promise<string[]> {
  chemicalLoading.value = true
  try {
    const data = await listChemicals({
      q: query.trim() !== '' ? query.trim() : undefined,
      query_type: 'name',
      page: 1,
      page_size: 50,
    })
    return buildChemicalNameOptions(data.items)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
    return []
  } finally {
    chemicalLoading.value = false
  }
}

function chemicalNameSource(query: string, process: (choices: string[]) => void) {
  void loadChemicalNames(query).then((choices) => {
    process(choices)
  })
}

function buildChemicalNameOptions(rows: ChemicalRow[]): string[] {
  const options = new Set<string>()
  for (const row of rows) {
    const name = String(row.substance || row.substance_english_name || '').trim()
    if (name !== '') {
      options.add(name)
    }
  }
  return Array.from(options)
}

async function saveTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    templateData.value = await saveReactionTemplate(templateData.value)
    persistTemplateDraft()
    ElMessage.success('模板已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function runResourceCheck() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await checkResource(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('物料核算已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function submitTemplate() {
  if (templateData.value === null) {
    return
  }
  try {
    const data = await submitReactionTemplate(templateData.value)
    currentJobId.value = data.job_id
    ElMessage.success('提交任务已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function onJobFinished(_job: JobState) {
  loadTemplate(false)
}

function isYesNoParam(name: string): boolean {
  return ['等待目标温度', '固定加料顺序', '自动加磁子'].includes(name)
}

function isReactorParam(name: string): boolean {
  return name === '反应器类型'
}

function isReagentNameColumn(header: string, index: number): boolean {
  if (index === 0) {
    return false
  }
  return header.includes('试剂') && header.includes('量') === false
}

function setExperimentCount(count: number) {
  if (templateData.value === null) {
    return
  }
  const width = templateData.value.headers.length
  const nextRows: unknown[][] = []
  for (let index = 0; index < count; index += 1) {
    const source = templateData.value.rows[index]
    const row = Array.isArray(source) ? [...source] : []
    while (row.length < width) {
      row.push('')
    }
    row[0] = index + 1
    nextRows.push(row.slice(0, width))
  }
  templateData.value.rows = nextRows
}

function addReagentPair() {
  if (templateData.value === null) {
    return
  }
  templateData.value.headers.push('试剂', '试剂量')
  for (const row of templateData.value.rows) {
    row.push('', '')
  }
  templateData.value.reagent_pair_count += 1
}

function removeReagentPair() {
  if (templateData.value === null) {
    return
  }
  if (templateData.value.reagent_pair_count <= 1) {
    ElMessage.warning('至少保留一组试剂列')
    return
  }
  templateData.value.headers.splice(templateData.value.headers.length - 2, 2)
  for (const row of templateData.value.rows) {
    row.splice(row.length - 2, 2)
  }
  templateData.value.reagent_pair_count -= 1
}

function updateTemplateRows(rows: SpreadsheetRow[]) {
  if (templateData.value === null) {
    return
  }
  const width = templateData.value.headers.length
  templateData.value.rows = rows.map((row, rowIndex) => {
    const nextRow = normalizeSpreadsheetRow(row, width)
    nextRow[0] = rowIndex + 1
    return nextRow
  })
}

function setTemplateData(data: ReactionTemplate) {
  skipTemplatePersist = true
  templateData.value = data
  void nextTick(() => {
    skipTemplatePersist = false
  })
}

function readTemplateDraft(remoteTemplate: ReactionTemplate): ReactionTemplate | null {
  try {
    const rawDraft = localStorage.getItem(TASK_EDITOR_DRAFT_KEY)
    if (rawDraft === null) {
      return null
    }
    const draft = JSON.parse(rawDraft) as ReactionTemplate
    if (isCompatibleTemplateDraft(remoteTemplate, draft) === false) {
      return null
    }
    return draft
  } catch {
    return null
  }
}

function isCompatibleTemplateDraft(remoteTemplate: ReactionTemplate, draft: ReactionTemplate): boolean {
  if (Array.isArray(draft.headers) === false || Array.isArray(draft.rows) === false) {
    return false
  }
  return draft.headers.join('|') === remoteTemplate.headers.join('|')
}

function persistTemplateDraft() {
  if (templateData.value === null || skipTemplatePersist === true) {
    return
  }
  localStorage.setItem(TASK_EDITOR_DRAFT_KEY, JSON.stringify(templateData.value))
}

function clearTemplateDraft() {
  localStorage.removeItem(TASK_EDITOR_DRAFT_KEY)
}

function normalizeSpreadsheetRow(row: SpreadsheetRow, width: number): unknown[] {
  const values = Array.isArray(row) === true ? [...row] : []
  while (values.length < width) {
    values.push('')
  }
  return values.slice(0, width)
}

onMounted(() => {
  loadTemplate()
})

watch(
  templateData,
  () => {
    persistTemplateDraft()
  },
  { deep: true },
)
</script>

<template>
  <div class="view-stack" v-loading="loading">
    <section class="panel editor-settings-panel">
      <div class="panel-title">
        <h2>任务设定</h2>
        <div class="button-row">
          <el-select
            :model-value="experimentCount"
            style="width: 128px"
            @change="setExperimentCount"
          >
            <el-option
              v-for="count in templateData?.supported_experiment_counts || [12, 24, 36, 48]"
              :key="count"
              :label="String(count) + ' 个实验'"
              :value="count"
            />
          </el-select>
          <el-button :icon="Refresh" @click="loadTemplate(false)">重载</el-button>
          <el-button type="primary" :icon="DocumentChecked" @click="saveTemplate">保存</el-button>
          <el-button type="warning" :icon="CircleCheck" @click="runResourceCheck">物料核算</el-button>
          <el-button type="success" :icon="Upload" @click="submitTemplate">提交任务</el-button>
        </div>
      </div>

      <div v-if="templateData !== null" class="settings-grid">
        <template v-for="item in templateData.param_rows" :key="item.name">
          <div v-if="item.type === 'section'" class="settings-section">{{ item.name }}</div>
          <el-form-item v-else :label="item.name" class="settings-item">
            <el-select v-if="isYesNoParam(item.name)" v-model="item.value" style="width: 100%">
              <el-option label="是" value="是" />
              <el-option label="否" value="否" />
            </el-select>
            <el-select v-else-if="isReactorParam(item.name)" v-model="item.value" style="width: 100%">
              <el-option label="heat" value="heat" />
            </el-select>
            <el-input v-else v-model="item.value" />
          </el-form-item>
        </template>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>试剂表格</h2>
        <div class="button-row">
          <el-button :icon="Plus" @click="addReagentPair">试剂列</el-button>
          <el-button :icon="Minus" @click="removeReagentPair">试剂列</el-button>
        </div>
      </div>

      <div v-if="templateData !== null" class="spreadsheet-wrap">
        <EditableSpreadsheet
          :key="spreadsheetKey"
          :model-value="templateData.rows"
          :col-headers="templateData.headers"
          :columns="spreadsheetColumns"
          :height="520"
          @update:model-value="updateTemplateRows"
        />
      </div>
    </section>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" @finished="onJobFinished" />
  </div>
</template>

<style scoped>
.editor-settings-panel {
  position: relative;
  z-index: 2;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(210px, 1fr));
  gap: 10px 14px;
  align-items: start;
}

.settings-section {
  grid-column: 1 / -1;
  padding: 8px 12px;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  background: #eef4fb;
}

.settings-item {
  margin-bottom: 0;
}

.spreadsheet-wrap {
  width: 100%;
  min-height: 360px;
}

@media (max-width: 1100px) {
  .settings-grid {
    grid-template-columns: repeat(2, minmax(210px, 1fr));
  }
}

@media (max-width: 640px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
