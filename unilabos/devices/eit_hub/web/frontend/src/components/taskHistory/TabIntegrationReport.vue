<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Picture, Refresh, Right, ZoomIn } from '@element-plus/icons-vue'
import {
  fetchIntegrationReport,
  imageUrl,
  type AlignmentEntry,
  type CompoundCandidate,
  type FidPeak,
  type IntegrationReportResponse,
  type IntegrationSample,
  type TicPeak,
} from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'

const props = defineProps<{ taskId: number; reloadToken?: number }>()

const data = ref<IntegrationReportResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const selectedSampleName = ref<string | null>(null)
const innerTab = ref<'tic' | 'fid' | 'align'>('tic')
const selectedTicPeak = ref<TicPeak | null>(null)
const selectedFidPeak = ref<FidPeak | null>(null)
const selectedAlignment = ref<AlignmentEntry | null>(null)
const imageVersion = ref(0)

function nextRefreshKey(): number {
  const now = Date.now()
  if (now <= imageVersion.value) {
    return imageVersion.value + 1
  }
  return now
}

function clearPeakSelection(): void {
  selectedTicPeak.value = null
  selectedFidPeak.value = null
  selectedAlignment.value = null
}

async function load(taskId: number, preserveSample: boolean): Promise<void> {
  if (taskId <= 0) {
    return
  }
  const previousSampleName = preserveSample ? selectedSampleName.value : null
  const refreshKey = nextRefreshKey()
  loading.value = true
  errorMessage.value = ''
  if (preserveSample === false) {
    selectedSampleName.value = null
  }
  clearPeakSelection()
  try {
    data.value = await fetchIntegrationReport(taskId, refreshKey)
    imageVersion.value = refreshKey
    if (
      previousSampleName !== null &&
      data.value.samples.some((entry) => entry.name === previousSampleName)
    ) {
      selectedSampleName.value = previousSampleName
    } else if (data.value.samples.length > 0) {
      selectedSampleName.value = data.value.samples[0].name
    } else {
      selectedSampleName.value = null
    }
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

function reload(): void {
  void load(props.taskId, true)
}

watch(
  () => props.taskId,
  (taskId) => { void load(taskId, false) },
  { immediate: true },
)

watch(
  () => props.reloadToken,
  (token, oldToken) => {
    if (token === undefined || token === oldToken) {
      return
    }
    void load(props.taskId, true)
  },
)

const samples = computed(() => data.value?.samples ?? [])

const selectedSample = computed<IntegrationSample | null>(() => {
  if (selectedSampleName.value === null || data.value === null) {
    return null
  }
  return data.value.samples.find((entry) => entry.name === selectedSampleName.value) ?? null
})

watch(selectedSample, () => {
  clearPeakSelection()
})

function selectSample(name: string): void {
  selectedSampleName.value = name
}

function formatNumber(value: unknown, digits = 3): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(digits)
}

function formatPercent(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `${value.toFixed(2)}%`
}

function formatLargeNumber(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  if (Math.abs(value) >= 1e6) {
    return value.toExponential(3)
  }
  return value.toLocaleString()
}

function plotsImageUrl(filename: string | null): string | null {
  if (filename === null) {
    return null
  }
  return imageUrl(props.taskId, 'plots', filename, imageVersion.value)
}

function msImageUrl(filename: string | null): string | null {
  if (filename === null) {
    return null
  }
  return imageUrl(props.taskId, 'ms_plots', filename, imageVersion.value)
}

function structureImageUrl(filename: string | null): string | null {
  if (filename === null) {
    return null
  }
  return imageUrl(props.taskId, 'structures', filename, imageVersion.value)
}
</script>

<template>
  <div v-loading="loading" class="integration-tab">
    <header class="report-toolbar">
      <el-button :icon="Refresh" :loading="loading" size="small" @click="reload">重新加载</el-button>
    </header>
    <el-empty v-if="errorMessage !== '' && data === null" :description="errorMessage" />
    <template v-else-if="data !== null">
      <section class="sample-grid">
        <article
          v-for="sample in samples"
          :key="sample.name"
          class="sample-card"
          :class="{ active: sample.name === selectedSampleName }"
          @click="selectSample(sample.name)"
        >
          <header class="sample-head">
            <span class="sample-name">{{ sample.name }}</span>
            <span class="sample-peaks">
              <el-tag size="small" type="success" effect="plain">TIC × {{ sample.tic_peak_count ?? 0 }}</el-tag>
              <el-tag size="small" type="warning" effect="plain">FID × {{ sample.fid_peak_count ?? 0 }}</el-tag>
            </span>
          </header>
          <footer class="sample-footer">
            <span>面积 {{ formatLargeNumber(sample.tic_total_area) }}</span>
            <span class="acquired-at">{{ sample.acquired_at ?? '-' }}</span>
          </footer>
        </article>
      </section>

      <section v-if="selectedSample !== null" class="sample-detail">
        <header class="detail-header">
          <h3>{{ selectedSample.name }}</h3>
          <span class="meta-text">采集时间 {{ selectedSample.acquired_at ?? '-' }}</span>
        </header>

        <el-tabs v-model="innerTab" class="inner-tabs">
          <!-- TIC Tab -->
          <el-tab-pane label="TIC 色谱" name="tic">
            <div class="chrom-block">
              <el-image
                v-if="plotsImageUrl(selectedSample.tic_image) !== null"
                :src="plotsImageUrl(selectedSample.tic_image) ?? ''"
                :preview-src-list="[plotsImageUrl(selectedSample.tic_image) ?? '']"
                preview-teleported
                fit="contain"
                class="chrom-image"
              >
                <template #error>
                  <div class="empty-block">TIC 色谱图加载失败</div>
                </template>
              </el-image>
              <div v-else class="empty-block">
                <el-icon><Picture /></el-icon>
                <span>无 TIC 色谱图</span>
              </div>
            </div>

            <div class="peak-area">
              <aside class="peak-list">
                <h4 class="peak-title">TIC 峰列表 ({{ selectedSample.tic_peaks.length }})</h4>
                <ul>
                  <li
                    v-for="peak in selectedSample.tic_peaks"
                    :key="`tic-${peak.peak_no}`"
                    :class="{ active: selectedTicPeak?.peak_no === peak.peak_no }"
                    @click="selectedTicPeak = peak"
                  >
                    <span class="peak-no">峰 {{ peak.peak_no }}</span>
                    <span class="peak-rt">RT {{ formatNumber(peak.rt) }}</span>
                    <span class="peak-pct">{{ formatPercent(peak.area_pct) }}</span>
                    <el-icon class="peak-arrow"><Right /></el-icon>
                  </li>
                  <li v-if="selectedSample.tic_peaks.length === 0" class="peak-empty">无 TIC 峰</li>
                </ul>
              </aside>
              <main class="peak-detail">
                <template v-if="selectedTicPeak === null">
                  <div class="hint">
                    <el-icon><ZoomIn /></el-icon>
                    <span>从左侧选择一个 TIC 峰查看详情</span>
                  </div>
                </template>
                <template v-else>
                  <div class="peak-detail-grid">
                    <div class="ms-image-area">
                      <h4>峰 {{ selectedTicPeak.peak_no }} 质谱图</h4>
                      <el-image
                        v-if="msImageUrl(selectedTicPeak.ms_image) !== null"
                        :src="msImageUrl(selectedTicPeak.ms_image) ?? ''"
                        :preview-src-list="[msImageUrl(selectedTicPeak.ms_image) ?? '']"
                        preview-teleported
                        fit="contain"
                        class="ms-image"
                      >
                        <template #error>
                          <div class="ms-empty">质谱图加载失败</div>
                        </template>
                      </el-image>
                      <div v-else class="ms-empty">
                        <el-icon><Picture /></el-icon>
                        <span>无质谱图</span>
                      </div>
                    </div>
                    <div class="peak-stats">
                      <h4>峰参数</h4>
                      <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="保留时间(min)">{{ formatNumber(selectedTicPeak.rt) }}</el-descriptions-item>
                        <el-descriptions-item label="峰高">{{ formatLargeNumber(selectedTicPeak.height) }}</el-descriptions-item>
                        <el-descriptions-item label="峰面积">{{ formatLargeNumber(selectedTicPeak.area) }}</el-descriptions-item>
                        <el-descriptions-item label="面积%">{{ formatPercent(selectedTicPeak.area_pct) }}</el-descriptions-item>
                        <el-descriptions-item label="峰起始/结束(min)">
                          {{ formatNumber(selectedTicPeak.start) }} - {{ formatNumber(selectedTicPeak.end) }}
                        </el-descriptions-item>
                        <el-descriptions-item label="峰宽(min)">{{ formatNumber(selectedTicPeak.width) }}</el-descriptions-item>
                      </el-descriptions>
                      <h4 class="prediction-title">分子量预测</h4>
                      <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="PIM 预测">
                          {{ selectedTicPeak.pim_mw ?? '-' }} (置信 {{ formatNumber(selectedTicPeak.pim_confidence, 4) }})
                        </el-descriptions-item>
                        <el-descriptions-item label="SS-HM 预测">
                          {{ selectedTicPeak.sshm_mw ?? '-' }} (置信 {{ formatNumber(selectedTicPeak.sshm_confidence, 4) }})
                        </el-descriptions-item>
                      </el-descriptions>
                    </div>
                    <div class="candidates">
                      <h4>NIST 候选化合物</h4>
                      <div v-if="selectedTicPeak.candidates.length === 0" class="ms-empty">无候选化合物</div>
                      <div v-else class="candidate-list">
                        <article
                          v-for="candidate in selectedTicPeak.candidates"
                          :key="candidate.rank"
                          class="candidate-card"
                        >
                          <div class="candidate-image">
                            <el-image
                              v-if="structureImageUrl(candidate.structure_image) !== null"
                              :src="structureImageUrl(candidate.structure_image) ?? ''"
                              :preview-src-list="[structureImageUrl(candidate.structure_image) ?? '']"
                              preview-teleported
                              fit="contain"
                              class="structure-image"
                            >
                              <template #error>
                                <div class="structure-empty">无结构图</div>
                              </template>
                            </el-image>
                            <div v-else class="structure-empty">无结构图</div>
                          </div>
                          <div class="candidate-info">
                            <div class="candidate-head">
                              <el-tag size="small" :type="candidate.rank === 1 ? 'success' : 'info'">
                                匹配 #{{ candidate.rank }}
                              </el-tag>
                              <span class="candidate-score">匹配度 {{ formatNumber(candidate.score, 1) }}</span>
                            </div>
                            <div class="candidate-name">{{ candidate.name }}</div>
                            <div class="candidate-meta">
                              <span>{{ candidate.formula ?? '-' }}</span>
                              <span>MW {{ candidate.molecular_weight ?? '-' }}</span>
                            </div>
                          </div>
                        </article>
                      </div>
                    </div>
                  </div>
                </template>
              </main>
            </div>
          </el-tab-pane>

          <!-- FID Tab -->
          <el-tab-pane label="FID 色谱" name="fid">
            <div class="chrom-block">
              <el-image
                v-if="plotsImageUrl(selectedSample.fid_image) !== null"
                :src="plotsImageUrl(selectedSample.fid_image) ?? ''"
                :preview-src-list="[plotsImageUrl(selectedSample.fid_image) ?? '']"
                preview-teleported
                fit="contain"
                class="chrom-image"
              >
                <template #error>
                  <div class="empty-block">FID 色谱图加载失败</div>
                </template>
              </el-image>
              <div v-else class="empty-block">
                <el-icon><Picture /></el-icon>
                <span>无 FID 色谱图</span>
              </div>
            </div>

            <div class="peak-area">
              <aside class="peak-list">
                <h4 class="peak-title">FID 峰列表 ({{ selectedSample.fid_peaks.length }})</h4>
                <ul>
                  <li
                    v-for="peak in selectedSample.fid_peaks"
                    :key="`fid-${peak.peak_no}`"
                    :class="{ active: selectedFidPeak?.peak_no === peak.peak_no }"
                    @click="selectedFidPeak = peak"
                  >
                    <span class="peak-no">峰 {{ peak.peak_no }}</span>
                    <span class="peak-rt">RT {{ formatNumber(peak.rt) }}</span>
                    <span class="peak-pct">{{ formatPercent(peak.area_pct) }}</span>
                    <el-icon class="peak-arrow"><Right /></el-icon>
                  </li>
                  <li v-if="selectedSample.fid_peaks.length === 0" class="peak-empty">无 FID 峰</li>
                </ul>
              </aside>
              <main class="peak-detail">
                <template v-if="selectedFidPeak === null">
                  <div class="hint">
                    <el-icon><ZoomIn /></el-icon>
                    <span>从左侧选择一个 FID 峰查看详情</span>
                  </div>
                </template>
                <template v-else>
                  <div class="fid-detail">
                    <h4>峰 {{ selectedFidPeak.peak_no }} 参数</h4>
                    <el-descriptions :column="2" border size="small">
                      <el-descriptions-item label="保留时间(min)">{{ formatNumber(selectedFidPeak.rt) }}</el-descriptions-item>
                      <el-descriptions-item label="峰宽(min)">{{ formatNumber(selectedFidPeak.width) }}</el-descriptions-item>
                      <el-descriptions-item label="峰高">{{ formatLargeNumber(selectedFidPeak.height) }}</el-descriptions-item>
                      <el-descriptions-item label="面积%">{{ formatPercent(selectedFidPeak.area_pct) }}</el-descriptions-item>
                      <el-descriptions-item label="峰面积" :span="2">{{ formatLargeNumber(selectedFidPeak.area) }}</el-descriptions-item>
                      <el-descriptions-item label="峰起始/结束(min)" :span="2">
                        {{ formatNumber(selectedFidPeak.start) }} - {{ formatNumber(selectedFidPeak.end) }}
                      </el-descriptions-item>
                    </el-descriptions>
                  </div>
                </template>
              </main>
            </div>
          </el-tab-pane>

          <!-- TIC-FID 对照 Tab -->
          <el-tab-pane :label="`TIC-FID 对照 (${selectedSample.alignments.length})`" name="align">
            <div class="dual-chrom">
              <div class="chrom-block">
                <h4 class="chrom-title">TIC 色谱</h4>
                <el-image
                  v-if="plotsImageUrl(selectedSample.tic_image) !== null"
                  :src="plotsImageUrl(selectedSample.tic_image) ?? ''"
                  :preview-src-list="[plotsImageUrl(selectedSample.tic_image) ?? '', plotsImageUrl(selectedSample.fid_image) ?? '']"
                  preview-teleported
                  fit="contain"
                  class="chrom-image-small"
                >
                  <template #error>
                    <div class="empty-block">无 TIC</div>
                  </template>
                </el-image>
                <div v-else class="empty-block">无 TIC 色谱</div>
              </div>
              <div class="chrom-block">
                <h4 class="chrom-title">FID 色谱</h4>
                <el-image
                  v-if="plotsImageUrl(selectedSample.fid_image) !== null"
                  :src="plotsImageUrl(selectedSample.fid_image) ?? ''"
                  :preview-src-list="[plotsImageUrl(selectedSample.tic_image) ?? '', plotsImageUrl(selectedSample.fid_image) ?? '']"
                  preview-teleported
                  fit="contain"
                  class="chrom-image-small"
                >
                  <template #error>
                    <div class="empty-block">无 FID</div>
                  </template>
                </el-image>
                <div v-else class="empty-block">无 FID 色谱</div>
              </div>
            </div>

            <div class="peak-area">
              <aside class="peak-list">
                <h4 class="peak-title">FID-TIC 对照配对 ({{ selectedSample.alignments.length }})</h4>
                <ul>
                  <li
                    v-for="(align, idx) in selectedSample.alignments"
                    :key="`align-${idx}`"
                    :class="{ active: selectedAlignment === align }"
                    @click="selectedAlignment = align"
                  >
                    <span class="peak-no">FID {{ align.fid_peak_no }}</span>
                    <span class="peak-rt">↔ TIC {{ align.tic_peak_no ?? '—' }}</span>
                    <span class="peak-pct">{{ formatNumber(align.fid_rt) }}</span>
                    <el-icon class="peak-arrow"><Right /></el-icon>
                  </li>
                  <li v-if="selectedSample.alignments.length === 0" class="peak-empty">无对照数据</li>
                </ul>
              </aside>
              <main class="peak-detail">
                <template v-if="selectedAlignment === null">
                  <div class="hint">
                    <el-icon><ZoomIn /></el-icon>
                    <span>从左侧选择一个对照配对查看详情</span>
                  </div>
                </template>
                <template v-else>
                  <div class="peak-detail-grid">
                    <div class="ms-image-area">
                      <h4>对应 TIC 峰 {{ selectedAlignment.tic_peak_no ?? '—' }} 质谱图</h4>
                      <el-image
                        v-if="msImageUrl(selectedAlignment.ms_image) !== null"
                        :src="msImageUrl(selectedAlignment.ms_image) ?? ''"
                        :preview-src-list="[msImageUrl(selectedAlignment.ms_image) ?? '']"
                        preview-teleported
                        fit="contain"
                        class="ms-image"
                      >
                        <template #error>
                          <div class="ms-empty">质谱图加载失败</div>
                        </template>
                      </el-image>
                      <div v-else class="ms-empty">
                        <el-icon><Picture /></el-icon>
                        <span>无对应质谱图 (FID 独立峰, 无 TIC 配对)</span>
                      </div>
                    </div>
                    <div class="peak-stats">
                      <h4>对照参数</h4>
                      <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="FID 峰号">{{ selectedAlignment.fid_peak_no ?? '-' }}</el-descriptions-item>
                        <el-descriptions-item label="FID RT(min)">{{ formatNumber(selectedAlignment.fid_rt) }}</el-descriptions-item>
                        <el-descriptions-item label="FID 面积">{{ formatLargeNumber(selectedAlignment.fid_area) }}</el-descriptions-item>
                        <el-descriptions-item label="TIC 峰号">{{ selectedAlignment.tic_peak_no ?? '-' }}</el-descriptions-item>
                        <el-descriptions-item label="TIC RT(min)">{{ formatNumber(selectedAlignment.tic_rt) }}</el-descriptions-item>
                      </el-descriptions>
                      <h4 class="prediction-title">分子量预测</h4>
                      <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="PIM 预测">
                          {{ selectedAlignment.pim_mw ?? '-' }} (置信 {{ formatNumber(selectedAlignment.pim_confidence, 4) }})
                        </el-descriptions-item>
                        <el-descriptions-item label="SS-HM 预测">
                          {{ selectedAlignment.sshm_mw ?? '-' }} (置信 {{ formatNumber(selectedAlignment.sshm_confidence, 4) }})
                        </el-descriptions-item>
                      </el-descriptions>
                    </div>
                    <div class="candidates">
                      <h4>NIST 候选化合物 (基于 TIC 峰匹配)</h4>
                      <div v-if="selectedAlignment.candidates.length === 0" class="ms-empty">
                        无候选化合物 (FID 独立峰未匹配 TIC)
                      </div>
                      <div v-else class="candidate-list">
                        <article
                          v-for="candidate in selectedAlignment.candidates"
                          :key="candidate.rank"
                          class="candidate-card"
                        >
                          <div class="candidate-image">
                            <el-image
                              v-if="structureImageUrl(candidate.structure_image) !== null"
                              :src="structureImageUrl(candidate.structure_image) ?? ''"
                              :preview-src-list="[structureImageUrl(candidate.structure_image) ?? '']"
                              preview-teleported
                              fit="contain"
                              class="structure-image"
                            >
                              <template #error>
                                <div class="structure-empty">无结构图</div>
                              </template>
                            </el-image>
                            <div v-else class="structure-empty">无结构图</div>
                          </div>
                          <div class="candidate-info">
                            <div class="candidate-head">
                              <el-tag size="small" :type="candidate.rank === 1 ? 'success' : 'info'">
                                匹配 #{{ candidate.rank }}
                              </el-tag>
                              <span class="candidate-score">匹配度 {{ formatNumber(candidate.score, 1) }}</span>
                            </div>
                            <div class="candidate-name">{{ candidate.name }}</div>
                            <div class="candidate-meta">
                              <span>{{ candidate.formula ?? '-' }}</span>
                              <span>MW {{ candidate.molecular_weight ?? '-' }}</span>
                            </div>
                          </div>
                        </article>
                      </div>
                    </div>
                  </div>
                </template>
              </main>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>
    </template>
  </div>
</template>

<style scoped>
.integration-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
}

.report-toolbar {
  display: flex;
  justify-content: flex-end;
}

.sample-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}

.sample-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.sample-card:hover {
  box-shadow: var(--el-box-shadow-light);
  border-color: var(--el-color-primary-light-5);
}

.sample-card.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.sample-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.sample-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.sample-peaks {
  display: flex;
  gap: 4px;
}

.sample-footer {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.acquired-at {
  font-family: var(--el-font-family-monospace, monospace);
}

.sample-detail {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}

.detail-header h3 {
  margin: 0;
  font-size: 16px;
}

.meta-text {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.inner-tabs :deep(.el-tabs__content) {
  padding-top: 12px;
}

.chrom-block {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 12px;
}

.chrom-title {
  margin: 0 0 6px 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.chrom-image {
  display: block;
  width: 100%;
  height: auto;
  background: var(--el-fill-color-blank);
  border-radius: 4px;
  cursor: zoom-in;
}

.chrom-image-small {
  display: block;
  width: 100%;
  height: auto;
  background: var(--el-fill-color-blank);
  border-radius: 4px;
  cursor: zoom-in;
}

.chrom-image :deep(.el-image__inner),
.chrom-image-small :deep(.el-image__inner) {
  display: block;
  width: 100%;
  height: auto;
}

.dual-chrom {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.empty-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 32px 0;
  color: var(--el-text-color-secondary);
}

.peak-area {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}

.peak-list {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 8px;
  max-height: 460px;
  overflow-y: auto;
}

.peak-title {
  margin: 4px 0 8px 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.peak-list ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.peak-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}

.peak-list li:hover {
  background: var(--el-color-primary-light-9);
}

.peak-list li.active {
  background: var(--el-color-primary-light-8);
  font-weight: 600;
}

.peak-no {
  font-weight: 600;
  color: var(--el-color-primary);
  min-width: 50px;
}

.peak-rt {
  flex: 1;
  font-family: var(--el-font-family-monospace, monospace);
}

.peak-pct {
  color: var(--el-text-color-secondary);
}

.peak-arrow {
  color: var(--el-text-color-disabled);
}

.peak-empty {
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 16px;
  cursor: default !important;
}

.peak-empty:hover {
  background: transparent !important;
}

.peak-detail {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
  min-height: 320px;
}

.peak-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.peak-detail-grid h4, .fid-detail h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--el-color-primary);
}

.ms-image-area, .peak-stats, .candidates, .fid-detail {
  background: var(--el-fill-color-blank);
  border-radius: 6px;
  padding: 12px;
}

.candidates {
  grid-column: span 2;
}

.ms-image {
  width: 100%;
  height: 220px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  cursor: zoom-in;
}

.ms-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 32px 16px;
  color: var(--el-text-color-secondary);
  text-align: center;
  background: var(--el-fill-color-blank);
  border-radius: 6px;
}

.prediction-title {
  margin-top: 12px !important;
}

.candidate-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.candidate-card {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 10px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px;
}

.candidate-image {
  width: 100%;
  height: 100px;
  background: var(--el-fill-color-blank);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.structure-image {
  width: 100%;
  height: 100%;
  cursor: zoom-in;
}

.structure-empty {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: center;
}

.candidate-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.candidate-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.candidate-score {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.candidate-name {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  word-break: break-word;
}

.candidate-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: var(--el-font-family-monospace, monospace);
  margin-top: auto;
}

.hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 16px;
  color: var(--el-text-color-secondary);
}
</style>
