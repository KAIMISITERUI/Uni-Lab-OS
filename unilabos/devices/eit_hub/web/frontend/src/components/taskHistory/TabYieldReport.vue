<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchYieldReport,
  type YieldReportResponse,
  type YieldResultEntry,
} from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'
import StructurePreview from '../StructurePreview.vue'

const props = defineProps<{ taskId: number }>()

const data = ref<YieldReportResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const selectedDetail = ref<{ sample: string; product: string; entry: YieldResultEntry } | null>(null)

async function load(taskId: number): Promise<void> {
  if (taskId <= 0) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  selectedDetail.value = null
  try {
    data.value = await fetchYieldReport(taskId)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
    data.value = null
    if (errorMessage.value.includes('未找到') === false) {
      ElMessage.error(errorMessage.value)
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => props.taskId,
  (taskId) => { void load(taskId) },
  { immediate: true },
)

const products = computed(() => data.value?.products ?? [])
const samples = computed(() => data.value?.samples ?? [])
const config = computed(() => data.value?.config ?? null)

function findEntry(sampleEntry: { sample: string; results: YieldResultEntry[] }, productName: string): YieldResultEntry | null {
  return sampleEntry.results.find((entry) => entry.product_name === productName) ?? null
}

function yieldHeatColor(yieldPct: number | null): string {
  if (yieldPct === null) {
    return 'var(--el-fill-color-light)'
  }
  // 0..100 渐变: 红 -> 黄 -> 绿
  const clamped = Math.max(0, Math.min(100, yieldPct))
  const hue = clamped * 1.2  // 0=红, 60=黄, 120=绿
  return `hsl(${hue}, 70%, 88%)`
}

function selectCell(sample: string, productName: string, entry: YieldResultEntry | null): void {
  if (entry === null) {
    return
  }
  selectedDetail.value = { sample, product: productName, entry }
}

function formatNumber(value: unknown, digits = 3): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(digits)
}

function formatYield(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return '-'
  }
  return `${value.toFixed(2)}%`
}
</script>

<template>
  <div v-loading="loading" class="yield-tab">
    <el-empty v-if="errorMessage !== '' && data === null" :description="errorMessage" />
    <template v-else-if="data !== null && config !== null">
      <section class="config-area">
        <article class="config-card">
          <header><h4>反应配置</h4></header>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="计算方法">{{ config.calc_method ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="反应规模(mmol)">{{ config.reaction_scale ?? '-' }}</el-descriptions-item>
          </el-descriptions>
        </article>
        <article class="config-card">
          <header><h4>内标 · {{ config.internal_standard.name ?? '-' }}</h4></header>
          <div class="config-body">
            <StructurePreview
              v-if="config.internal_standard.smiles"
              :smiles="config.internal_standard.smiles"
              :width="200"
              :height="120"
            />
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="分子式">{{ config.internal_standard.formula ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="分子量">{{ formatNumber(config.internal_standard.molecular_weight, 3) }}</el-descriptions-item>
              <el-descriptions-item label="ECN">{{ config.internal_standard.ecn ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="用量(μL/mg)">{{ config.internal_standard.dosage ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="摩尔量(mmol)">{{ formatNumber(config.internal_standard.mmol, 4) }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </article>
        <article
          v-for="product in config.products"
          :key="product.product_index"
          class="config-card"
        >
          <header><h4>目标产物 #{{ product.product_index }} · {{ product.name ?? '-' }}</h4></header>
          <div class="config-body">
            <StructurePreview
              v-if="product.smiles"
              :smiles="product.smiles"
              :width="200"
              :height="120"
            />
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="分子式">{{ product.formula ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="分子量">{{ formatNumber(product.molecular_weight, 3) }}</el-descriptions-item>
              <el-descriptions-item label="ECN">{{ product.ecn ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="当量(eq)">{{ product.equivalent ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="适用实验">{{ product.applicable_experiments ?? '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </article>
      </section>

      <section class="matrix-area">
        <header class="matrix-head">
          <h3>产率热力图</h3>
          <span class="legend">
            <span class="legend-cell" :style="`background:${yieldHeatColor(0)};`">0%</span>
            <span class="legend-cell" :style="`background:${yieldHeatColor(50)};`">50%</span>
            <span class="legend-cell" :style="`background:${yieldHeatColor(100)};`">100%</span>
          </span>
        </header>
        <table v-if="samples.length > 0 && products.length > 0" class="heat-table">
          <thead>
            <tr>
              <th class="heat-corner">样品 \ 产物</th>
              <th v-for="product in products" :key="product">{{ product }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sampleEntry in samples" :key="sampleEntry.sample">
              <th class="row-head">{{ sampleEntry.sample }}</th>
              <td
                v-for="product in products"
                :key="sampleEntry.sample + ':' + product"
                class="heat-cell"
                :style="`background:${yieldHeatColor(findEntry(sampleEntry, product)?.yield_pct ?? null)};`"
                :class="{
                  active:
                    selectedDetail !== null &&
                    selectedDetail.sample === sampleEntry.sample &&
                    selectedDetail.product === product,
                }"
                @click="selectCell(sampleEntry.sample, product, findEntry(sampleEntry, product))"
              >
                <span class="yield-value">{{ formatYield(findEntry(sampleEntry, product)?.yield_pct ?? null) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <el-empty v-else description="无产率数据" />
      </section>

      <transition name="fade">
        <div v-if="selectedDetail !== null" class="entry-detail">
          <header>
            <h3>{{ selectedDetail.sample }} · {{ selectedDetail.product }}</h3>
            <el-button text size="small" @click="selectedDetail = null">关闭</el-button>
          </header>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="产率(%)">
              <el-tag
                size="small"
                :type="selectedDetail.entry.yield_pct === null ? 'info' : 'success'"
              >
                {{ formatYield(selectedDetail.entry.yield_pct) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Ratio">{{ formatNumber(selectedDetail.entry.ratio, 4) }}</el-descriptions-item>
            <el-descriptions-item label="产物 RT(min)">{{ formatNumber(selectedDetail.entry.product_rt) }}</el-descriptions-item>
            <el-descriptions-item label="产物 FID 面积">{{ formatNumber(selectedDetail.entry.product_area, 4) }}</el-descriptions-item>
            <el-descriptions-item label="产物匹配化合物">{{ selectedDetail.entry.product_match ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="产物 ECN">{{ selectedDetail.entry.product_ecn ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="内标 RT(min)">{{ formatNumber(selectedDetail.entry.internal_rt) }}</el-descriptions-item>
            <el-descriptions-item label="内标 FID 面积">{{ formatNumber(selectedDetail.entry.internal_area, 4) }}</el-descriptions-item>
            <el-descriptions-item label="内标匹配化合物">{{ selectedDetail.entry.internal_match ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="内标 ECN">{{ selectedDetail.entry.internal_ecn ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="匹配方式">{{ selectedDetail.entry.match_method ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="置信度">{{ formatNumber(selectedDetail.entry.confidence, 4) }}</el-descriptions-item>
            <el-descriptions-item label="NIST 分子量">{{ selectedDetail.entry.nist_mw ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="PIM 预测">{{ selectedDetail.entry.pim_mw ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="SS-HM 预测">{{ selectedDetail.entry.sshm_mw ?? '-' }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedDetail.entry.remarks" label="备注" :span="2">
              {{ selectedDetail.entry.remarks }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </transition>
    </template>
  </div>
</template>

<style scoped>
.yield-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
}

.config-area {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.config-card {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}

.config-card header h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--el-color-primary);
  word-break: break-word;
}

.config-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.matrix-area {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}

.matrix-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.matrix-head h3 {
  margin: 0;
  font-size: 16px;
}

.legend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.legend-cell {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-family: var(--el-font-family-monospace, monospace);
  font-size: 11px;
  color: var(--el-text-color-primary);
}

.heat-table {
  width: 100%;
  border-collapse: collapse;
}

.heat-table th, .heat-table td {
  padding: 8px;
  border: 1px solid var(--el-border-color-lighter);
  text-align: center;
  font-size: 13px;
}

.heat-corner, .row-head {
  background: var(--el-fill-color-light);
  font-weight: 600;
  position: sticky;
  left: 0;
}

.heat-cell {
  cursor: pointer;
  transition: outline 0.12s;
}

.heat-cell:hover {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: -2px;
}

.heat-cell.active {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

.yield-value {
  font-weight: 600;
  font-family: var(--el-font-family-monospace, monospace);
}

.entry-detail {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 6px;
  padding: 12px;
}

.entry-detail header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.entry-detail h3 {
  margin: 0;
  font-size: 15px;
  color: var(--el-color-primary);
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.15s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
