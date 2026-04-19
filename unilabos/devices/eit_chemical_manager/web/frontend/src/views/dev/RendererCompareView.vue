<script setup lang="ts">
/**
 * 功能:
 *     并排对比多个 SMILES 2D 渲染器对同一批分子的输出
 * 说明:
 *     - 行为测试分子, 列为候选渲染库
 *     - 每格展示 SVG + 渲染耗时, 异常时显示错误信息
 *     - 所有渲染器通过动态 import 按需加载, 不进入主业务 bundle
 *     - 评估结束后可直接删除本视图与 rendering composables
 */
import { reactive, ref, onMounted } from 'vue'
import { ElButton, ElInputNumber, ElTag, ElAlert, ElIcon } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import type { RendererEntry } from '../../composables/rendering/rendererTypes'

// 列定义: 第 1 列为 RDKit 作对照, 后三列为候选评估库
const renderers: RendererEntry[] = [
  {
    name: 'RDKit.js',
    note: '当前使用 (对照基准)',
    loader: () => import('../../composables/rendering/useRDKitAdapter'),
  },
  {
    name: 'OpenChemLib',
    note: '纯 JS, BSD',
    loader: () => import('../../composables/rendering/useOpenChemLib'),
  },
  {
    name: 'Indigo (Ketcher WASM)',
    note: 'WASM ~2MB, Apache 2.0',
    loader: () => import('../../composables/rendering/useIndigoKetcher'),
  },
  {
    name: 'Marvin JS',
    note: '商业库, 需许可证',
    loader: () => import('../../composables/rendering/useMarvin'),
  },
]

// 行定义: 取自用户截图中的代表性分子
interface Sample {
  name: string
  smiles: string
}

const samples: Sample[] = [
  { name: '苯甲酸', smiles: 'O=C(O)c1ccccc1' },
  { name: '反式肉桂醇', smiles: 'OC/C=C/c1ccccc1' },
  { name: '甘氨酸甲酯盐酸盐', smiles: 'COC(=O)CN.Cl' },
  { name: "1,1'-磺酰双咪唑", smiles: 'O=S(=O)(n1ccnc1)n1ccnc1' },
  { name: '对氯苯甲酸', smiles: 'O=C(O)c1ccc(Cl)cc1' },
  { name: '氨基磺酰胺', smiles: 'NS(N)(=O)=O' },
]

interface CellState {
  status: 'idle' | 'rendering' | 'success' | 'error'
  svg?: string
  ms?: number
  error?: string
}

// 画布尺寸, 与主业务常用尺寸接近 (详情弹窗用 500x400, 列表用 120x90)
const width = ref(280)
const height = ref(220)

// 渲染状态: 键格式 `${sampleIdx}|${rendererIdx}`
const cells = reactive<Record<string, CellState>>({})

function cellKey(i: number, j: number): string {
  return `${i}|${j}`
}

async function renderOne(i: number, j: number): Promise<void> {
  const key = cellKey(i, j)
  cells[key] = { status: 'rendering' }
  try {
    const mod = await renderers[j].loader()
    const t0 = performance.now()
    const svg = await mod.renderSmilesToSvg(
      samples[i].smiles,
      width.value,
      height.value,
    )
    const ms = Math.round(performance.now() - t0)
    cells[key] = { status: 'success', svg, ms }
  } catch (error) {
    const message =
      error instanceof Error ? error.message : String(error)
    cells[key] = { status: 'error', error: message }
  }
}

async function renderAll(): Promise<void> {
  // 所有格并行; 同一个 renderer 的多次调用共享 loader 单例
  const tasks: Array<Promise<void>> = []
  for (let i = 0; i < samples.length; i++) {
    for (let j = 0; j < renderers.length; j++) {
      tasks.push(renderOne(i, j))
    }
  }
  await Promise.all(tasks)
}

onMounted(() => {
  renderAll()
})
</script>

<template>
  <div class="renderer-compare">
    <header class="toolbar">
      <h2 class="title">SMILES 渲染器对比评估</h2>
      <div class="controls">
        <span class="label">宽</span>
        <el-input-number v-model="width" :min="80" :max="800" :step="20" size="small" />
        <span class="label">高</span>
        <el-input-number v-model="height" :min="80" :max="800" :step="20" size="small" />
        <el-button type="primary" size="small" @click="renderAll">重新渲染</el-button>
      </div>
      <p class="hint">
        Marvin JS 因商业许可证无法本地集成, 请前往
        <a href="https://marvinjs-demo.chemaxon.com/" target="_blank" rel="noopener">
          marvinjs-demo.chemaxon.com
        </a>
        使用同一批 SMILES 手工对比。
      </p>
    </header>

    <div class="grid">
      <div class="cell head">分子</div>
      <div v-for="r in renderers" :key="r.name" class="cell head">
        <div class="r-name">{{ r.name }}</div>
        <div v-if="r.note" class="r-note">{{ r.note }}</div>
      </div>

      <template v-for="(s, i) in samples" :key="s.smiles">
        <div class="cell meta">
          <div class="s-name">{{ s.name }}</div>
          <code class="s-smi">{{ s.smiles }}</code>
        </div>
        <div
          v-for="(_r, j) in renderers"
          :key="`${i}-${j}`"
          class="cell render"
        >
          <template v-if="cells[cellKey(i, j)]?.status === 'rendering'">
            <el-icon class="spin"><Loading /></el-icon>
          </template>
          <template v-else-if="cells[cellKey(i, j)]?.status === 'success'">
            <div class="svg-box" v-html="cells[cellKey(i, j)]!.svg" />
            <el-tag size="small" type="info">{{ cells[cellKey(i, j)]!.ms }} ms</el-tag>
          </template>
          <template v-else-if="cells[cellKey(i, j)]?.status === 'error'">
            <el-alert
              :title="cells[cellKey(i, j)]!.error"
              type="warning"
              :closable="false"
              show-icon
            />
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.renderer-compare {
  padding: 16px 24px;
}

.toolbar {
  margin-bottom: 16px;
}

.title {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #303133;
}

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.label {
  font-size: 13px;
  color: #606266;
}

.hint {
  margin: 0;
  color: #909399;
  font-size: 12px;
}

.hint a {
  color: #409eff;
}

.grid {
  display: grid;
  grid-template-columns: minmax(200px, 1fr) repeat(4, minmax(260px, 1fr));
  gap: 8px;
  align-items: stretch;
}

.cell {
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 8px;
  background: #fff;
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  /* 任何渲染器异常返回文本时不得溢出到邻列, min-width: 0 是 grid 子项收缩前提 */
  overflow: hidden;
  min-width: 0;
  word-break: break-all;
}

.cell.head {
  background: #f5f7fa;
  min-height: 48px;
  font-weight: 600;
}

.r-name {
  font-size: 14px;
  color: #303133;
}

.r-note {
  font-size: 11px;
  color: #909399;
  font-weight: normal;
  margin-top: 2px;
}

.cell.meta {
  align-items: flex-start;
  justify-content: flex-start;
}

.s-name {
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.s-smi {
  font-size: 12px;
  color: #606266;
  word-break: break-all;
  background: #fafafa;
  padding: 2px 4px;
  border-radius: 2px;
}

.cell.render {
  background: #fff;
}

.svg-box {
  display: flex;
  align-items: center;
  justify-content: center;
}

.svg-box :deep(svg) {
  max-width: 100%;
  height: auto;
}

.spin {
  animation: spin 1s linear infinite;
  font-size: 20px;
  color: #909399;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
