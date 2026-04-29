<template>
  <!--
    功能:
      录入资源对话框 (v2). 两栏布局对齐 web_code 截图:
        - 左栏 资源视图预览: 位置码标签栏 + 完整 NTU 工站 3D
        - 右栏 资源配置: 已选槽位卡片列表, 每个卡片含托盘型号下拉 + 条码 + 孔位网格
      底部 取消 / 确定 按钮. 提交时按 web_code addV2 逻辑组装 batchInTray payload.
  -->
  <el-dialog
    :model-value="visible"
    width="92%"
    top="3vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="true"
    append-to-body
    :z-index="5000"
    destroy-on-close
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <template #header>
      <div class="dialog-title">录入资源</div>
    </template>
    <div class="dialog-body" v-loading="loading">
      <div class="two-col">
        <div class="col col-left">
          <div class="step-title"><span class="step-dot"></span>资源视图预览</div>
          <div class="col-inner preview-inner">
            <StationPreview
              :selected-codes="selectedCodes"
              :slot-resources="stationPreviewResources"
              :visible-prefixes="visiblePrefixes"
              @slot-click="onSlotToggle"
              @remove-slot="onRemoveSlot"
              @station-ready="onStationReady"
            />
            <div class="loading-side-controls">
              <el-radio-group
                v-model="loadingSide"
                size="small"
                @change="onLoadingSideChange"
              >
                <el-radio-button value="W-1">W-1上料</el-radio-button>
                <el-radio-button value="TB">TB上料</el-radio-button>
              </el-radio-group>
            </div>
          </div>
        </div>
        <div class="col col-right">
          <div class="step-title"><span class="step-dot"></span>资源配置</div>
          <div class="col-inner scroll">
            <el-empty
              v-if="selectedConfigs.length === 0"
              description="请在左侧 3D 视图中点击空槽位"
              :image-size="80"
            />
            <SlotConfigCard
              v-for="conf in selectedConfigs"
              :key="conf.layoutCode"
              :config="conf"
              :tray-options="trayOptions"
              @remove="onRemoveSlot(conf.layoutCode)"
              @update:tray-model="(v) => onTrayModelChange(conf.layoutCode, v)"
              @update:tray-qr="(v) => onTrayQRChange(conf.layoutCode, v)"
              @update:wells="(v) => onWellsChange(conf.layoutCode, v)"
            />
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onCancel">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onConfirm">确定</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { batchInTray, getResourceInfo, type InTrayResource } from '@/api/synthesis'
import { getModule } from '@/lib/dynamic-graph'
import StationPreview, { type SlotResourcePreview } from './StationPreview.vue'
import SlotConfigCard from './SlotConfigCard.vue'
import type { SelectedSlotConfig, TrayModelOption, WellInfo, WellState } from './types'

type LoadingSide = 'W-1' | 'TB'

interface Props {
  visible: boolean
  initialLayoutCode?: string
}
const props = withDefaults(defineProps<Props>(), { initialLayoutCode: '' })
const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'success'): void
}>()

const loading = ref(false)
const submitting = ref(false)
const loadingSide = ref<LoadingSide>('W-1')

// 设备已占用槽位 (layout_code 集合), 阻止重复录入
const occupiedSet = reactive(new Set<string>())

// 选中槽位配置: layoutCode -> SelectedSlotConfig
const configMap = reactive<Record<string, SelectedSlotConfig>>({})
const selectedCodes = computed(() => Object.keys(configMap))
const selectedConfigs = computed(() => selectedCodes.value.map((c) => configMap[c]))
const visiblePrefixes = computed(() => {
  if (loadingSide.value === 'TB') {
    return ['TB-']
  }
  return ['W-1-']
})

// 汇总到 StationPreview 的 slot 资源预览, 让左侧大 3D 视图实时反映右侧填写状态
const stationPreviewResources = computed<SlotResourcePreview[]>(() => {
  return selectedConfigs.value.map((cfg) => {
    const opt = trayOptions.value.find((o) => o.model === cfg.trayModel)
    const vesselType = opt?.vesselModels?.[0] || cfg.trayModel
    return {
      layoutCode: cfg.layoutCode,
      trayModel: cfg.trayModel,
      vesselType,
      filledWells: cfg.wells
        .filter((w) => w.state === 'filled')
        .map((w) => ({
          slotIndex: w.slotIndex,
          with_cap: w.with_cap !== false,
          with_magneton: w.with_magneton === true,
        })),
    }
  })
})

const REMOVED_TRAY_MODEL = '201000503'
const W1_ONLY_TRAY_MODEL = '220000023'
const CAPLESS_TRAY_MODELS = new Set(['220000023', '201000728'])

// 可用托盘型号下拉选项, 来自 BaseTray 注册表
const allTrayOptions = ref<TrayModelOption[]>([])
const trayOptions = computed(() => allTrayOptions.value.filter((opt) => isTrayOptionAllowed(opt.model)))

watch(
  () => props.visible,
  (v) => {
    if (v) {
      // 每次打开清空已选, 用最新数据重建
      loadingSide.value = inferLoadingSide(props.initialLayoutCode)
      clearSelectedConfigs()
    }
  },
)

function loadTrayOptions (): void {
  // BaseTray.getAllModels 返回托盘实例数组, getModule 已按当前站点(NTU) 过滤过
  // 还要进一步排除 tray_front SVG 缺失的型号 (例如 50μL Tip 头托盘 201000815 的 SVG 在仓库里就不存在),
  // 否则下拉选中后缩略图会空白 + parseSVG 报错.
  try {
    const module = getModule()
    const all = module.BaseTray.getAllModels?.() || []
    const opts: TrayModelOption[] = []
    all.forEach((tray: any) => {
      const cfg = tray.config || {}
      const model = tray.model || cfg.model
      if (cfg.noAddin === true) { return }
      if (model === REMOVED_TRAY_MODEL) { return }
      // SVG 资源必须就绪, 否则不展示在下拉
      if (!cfg.tray_front) { return }
      opts.push({
        model,
        name: cfg.name || model,
        row: Number(cfg.row) || 0,
        col: Number(cfg.col) || 0,
        childrenCount: Number(cfg.children_count) || (Number(cfg.row) * Number(cfg.col)) || 0,
        vesselModels: Array.isArray(cfg.vessel_models) ? cfg.vessel_models : [],
        noAddin: cfg.noAddin === true,
        defaultWithCap: resolveDefaultWithCap(model, cfg),
        defaultWithMagneton: resolveDefaultWithMagneton(cfg),
        editSubstanceCreate: cfg.editSubstance?.create === true,
      })
    })
    opts.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'))
    allTrayOptions.value = opts
  } catch (err) {
    console.error('[ResourceAddDialog] loadTrayOptions failed:', err)
    allTrayOptions.value = []
  }
}

async function loadOccupied (): Promise<void> {
  occupiedSet.clear()
  try {
    const resp = await getResourceInfo({})
    const list = (resp?.resource_list as Array<Record<string, unknown>> | undefined) || []
    list.forEach((item) => {
      const code = item.layout_code as string | undefined
      if (typeof code === 'string') { occupiedSet.add(code) }
    })
  } catch (err) {
    console.warn('[ResourceAddDialog] getResourceInfo failed:', err)
  }
}

async function onStationReady (_station: any): Promise<void> {
  loading.value = true
  try {
    loadTrayOptions()
    await loadOccupied()
    if (props.initialLayoutCode) {
      addSlot(props.initialLayoutCode)
    }
  } finally {
    loading.value = false
  }
}

function clearSelectedConfigs (): void {
  Object.keys(configMap).forEach((k) => { delete configMap[k] })
}

function inferLoadingSide (layoutCode: string): LoadingSide {
  if (layoutCode.startsWith('TB-')) {
    return 'TB'
  }
  return 'W-1'
}

function isLayoutInCurrentSide (layoutCode: string): boolean {
  return visiblePrefixes.value.some((prefix) => layoutCode.startsWith(prefix))
}

function sideLabel (side: LoadingSide): string {
  if (side === 'TB') {
    return 'TB'
  }
  return 'W-1'
}

function isTrayOptionAllowed (model: string): boolean {
  if (model === REMOVED_TRAY_MODEL) {
    return false
  }
  if (loadingSide.value === 'TB' && model === W1_ONLY_TRAY_MODEL) {
    return false
  }
  return true
}

function resolveDefaultWithCap (model: string, cfg: Record<string, any>): boolean {
  if (CAPLESS_TRAY_MODELS.has(model)) {
    return false
  }
  if (typeof cfg.with_cap === 'boolean') {
    return cfg.with_cap
  }
  if (typeof cfg.with_cap?.NTU === 'boolean') {
    return cfg.with_cap.NTU
  }
  return true
}

function resolveDefaultWithMagneton (cfg: Record<string, any>): boolean {
  if (cfg.isMagnetonTray === true) {
    return true
  }
  if (typeof cfg.with_magneton === 'boolean') {
    return cfg.with_magneton
  }
  if (typeof cfg.with_magneton?.NTU === 'boolean') {
    return cfg.with_magneton.NTU
  }
  return false
}

function onLoadingSideChange (val: string | number | boolean): void {
  const nextSide: LoadingSide = val === 'TB' ? 'TB' : 'W-1'
  loadingSide.value = nextSide
  clearSelectedConfigs()
  ElMessage.info('已切换上料侧, 请重新选择槽位')
}

function addSlot (layoutCode: string): void {
  if (isLayoutInCurrentSide(layoutCode) === false) {
    ElMessage.warning(`当前为 ${sideLabel(loadingSide.value)} 上料, 只能选择对应侧槽位`)
    return
  }
  if (occupiedSet.has(layoutCode)) {
    ElMessage.warning(`槽位 ${layoutCode} 已被占用, 无法录入`)
    return
  }
  if (configMap[layoutCode] !== undefined) { return }
  configMap[layoutCode] = createConfig(layoutCode)
}

function createConfig (layoutCode: string): SelectedSlotConfig {
  return {
    layoutCode,
    trayModel: '',
    trayQRCode: '',
    remark: '',
    wells: [],
  }
}

function onSlotToggle (layoutCode: string): void {
  if (configMap[layoutCode] !== undefined) {
    delete configMap[layoutCode]
    return
  }
  addSlot(layoutCode)
}

function onRemoveSlot (layoutCode: string): void {
  delete configMap[layoutCode]
}

function onTrayModelChange (layoutCode: string, model: string): void {
  const cfg = configMap[layoutCode]
  if (cfg === undefined) { return }
  if (isTrayOptionAllowed(model) === false) {
    ElMessage.warning('当前上料侧不允许选择该托盘型号')
    return
  }
  cfg.trayModel = model
  cfg.wells = generateWells(model)
}

function onTrayQRChange (layoutCode: string, val: string): void {
  const cfg = configMap[layoutCode]
  if (cfg === undefined) { return }
  cfg.trayQRCode = val
}

function onWellsChange (layoutCode: string, wells: WellInfo[]): void {
  const cfg = configMap[layoutCode]
  if (cfg === undefined) { return }
  cfg.wells = wells
}

function generateWells (trayModel: string): WellInfo[] {
  const opt = trayOptions.value.find((o) => o.model === trayModel)
  if (opt === undefined) { return [] }
  const result: WellInfo[] = []
  // 物料/Tip 托盘 (editSubstanceCreate=false): 默认满盘, 用户从满到取
  // 试剂托盘 (editSubstanceCreate=true): 默认空盘, 用户逐个录入
  const initialState: WellState = opt.editSubstanceCreate ? 'empty' : 'filled'
  // 列优先 (column-major) 索引: 与 ntu-model.json layout {start:"lb", direction:"y"} 物理排布一致
  // 即 slotIndex 0=A1(底左), 1=A2(A 列向上), ..., row-1=A_top, row=B1, ...
  for (let c = 1; c <= opt.col; c++) {
    for (let r = 1; r <= opt.row; r++) {
      result.push({
        slotIndex: (c - 1) * opt.row + (r - 1),
        rowIndex: r,
        colIndex: c,
        rowLabel: String(r),
        colLabel: String.fromCharCode(64 + c),
        state: initialState,
        substance: '',
        unit: 'mg',
        amount: null,
        chemical_id: '',
        with_cap: opt.defaultWithCap,
        with_magneton: opt.defaultWithMagneton,
      })
    }
  }
  return result
}

async function onConfirm (): Promise<void> {
  if (selectedConfigs.value.length === 0) {
    ElMessage.warning('请至少选择一个槽位')
    return
  }
  for (const cfg of selectedConfigs.value) {
    if (!cfg.trayModel) {
      ElMessage.warning(`槽位 ${cfg.layoutCode} 未选择托盘型号`)
      return
    }
    if (isLayoutInCurrentSide(cfg.layoutCode) === false) {
      ElMessage.warning(`槽位 ${cfg.layoutCode} 不属于当前上料侧`)
      return
    }
    if (isTrayOptionAllowed(cfg.trayModel) === false) {
      ElMessage.warning(`槽位 ${cfg.layoutCode} 的托盘型号不允许从当前侧上料`)
      return
    }
    if (cfg.wells.every((w) => w.state !== 'filled')) {
      ElMessage.warning(`槽位 ${cfg.layoutCode} 未选择任何孔位`)
      return
    }
  }

  // 组装 payload, 形态对齐 web_code addV2 → /api/BatchInTray
  // 仅下发实际有值的字段, 用户没填的不出现在请求体里
  const resource_req_list = selectedConfigs.value.map((cfg) => {
    const opt = trayOptions.value.find((o) => o.model === cfg.trayModel)
    const defaultResType = opt?.vesselModels?.[0] || cfg.trayModel
    const resource_list: InTrayResource[] = cfg.wells
      .filter((w) => w.state === 'filled')
      .map((w) => {
        const item: InTrayResource = {
          layout_code: `${cfg.layoutCode}:${w.slotIndex}`,
          resource_type: defaultResType,
          substance: w.substance || '',
          slot_label: `${w.colLabel}${w.rowLabel}`,
          with_cap: w.with_cap,
        }
        if (w.with_magneton === true) {
          item.with_magneton = true
        }
        if (w.amount !== null && w.amount !== undefined) {
          item.amount = w.amount
          item.unit = w.unit
        }
        if (w.chemical_id) { item.chemical_id = w.chemical_id }
        return item
      })
    return {
      tray_layout_code: cfg.layoutCode,
      tray_type: cfg.trayModel,
      tray_QR_code: cfg.trayQRCode || undefined,
      resource_list,
    }
  })

  submitting.value = true
  try {
    await batchInTray({ resource_req_list })
    ElMessage.success('录入成功')
    emit('success')
    emit('update:visible', false)
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '录入失败'
    ElMessage.error(`录入失败: ${detail}`)
  } finally {
    submitting.value = false
  }
}

function onCancel (): void {
  emit('update:visible', false)
}
</script>

<style scoped>
.dialog-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.dialog-body {
  height: 78vh;
  background: #f5f7fb;
  padding: 8px;
  border-radius: 6px;
  overflow: hidden;
}
.two-col {
  display: grid;
  grid-template-columns: minmax(320px, 0.72fr) minmax(520px, 1.28fr);
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.col {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  padding: 6px 4px;
  flex: 0 0 auto;
}
.preview-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px;
}
.preview-inner :deep(.station-preview) {
  flex: 1 1 auto;
  min-height: 0;
  height: auto;
}
.loading-side-controls {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 2px;
}
.step-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0dbf75;
}
.col-inner {
  flex: 1 1 auto;
  min-height: 0;
  background: #fff;
  border-radius: 6px;
  padding: 10px;
  overflow: hidden;
}
.col-inner.scroll {
  overflow-y: auto;
  overflow-x: hidden;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
