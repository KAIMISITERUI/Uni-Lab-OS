<template>
  <!--
    功能:
      编辑资源对话框. 1:1 复刻截图布局:
        - 左栏 资源视图预览 (50%): 顶部 位置码 输入 + 完整 NTU 工站 3D (与移出资源同款),
                              支持多选: 点击有资源的托盘加入选中并染绿; 再次点击取消选中
        - 右栏 资源配置 (50%): 已选托盘列表, 每个托盘一张 SlotConfigCard (托盘类型只读 + 托盘条码 + 三态孔位 + 介质内物质表)
                              物质量从设备 cur_weight / cur_volume 字段读出
        - 底部红色警告: 为避免溶剂交叉污染, 请放置溶剂瓶前清洁溶剂库盖板!
      提交逻辑: 将已选托盘组装为 resource_req_list, 调用 /BatchUpdateResource 一次提交.
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
      <div class="dialog-title">编辑资源</div>
    </template>
    <div class="dialog-body" v-loading="loading">
      <div class="two-col">
        <div class="col col-left">
          <div class="step-title"><span class="step-dot"></span>资源视图预览</div>
          <div class="col-inner preview-inner">
            <div class="position-input-bar">
              <el-input
                v-model="positionInput"
                placeholder="位置码 (例: W-4-1, 回车选中 / 取消)"
                clearable
                :prefix-icon="iconLocation"
                @change="onPositionInputCommit"
                @keyup.enter="onPositionInputCommit"
              />
              <div class="tag-list">
                <el-tag
                  v-for="code in selectedCodes"
                  :key="code"
                  closable
                  type="success"
                  @close="onDeselect(code)"
                >
                  {{ code }}
                </el-tag>
              </div>
            </div>
            <NTUStationGraph
              ref="graphRef"
              :margin="24"
              :auto-select-on-click="false"
              :on-click-tray="onClickTray"
            />
          </div>
        </div>
        <div class="col col-right">
          <div class="step-title"><span class="step-dot"></span>资源配置</div>
          <div class="col-inner scroll">
            <el-empty
              v-if="selectedCodes.length === 0"
              :description="emptyDesc"
              :image-size="80"
            />
            <SlotConfigCard
              v-for="code in selectedCodes"
              v-else
              :key="code"
              :config="configMap[code]"
              :tray-options="trayOptions"
              :readonly-tray-model="true"
              :allow-disabled="allowDisabledForConfig(configMap[code])"
              @remove="onDeselect(code)"
              @update:tray-qr="(v) => onTrayQRChange(code, v)"
              @update:wells="(v) => onWellsChange(code, v)"
            />
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <div class="footer-left">
          <span class="warning-icon">!</span>
          <span class="warning-tip">为避免溶剂交叉污染, 请放置溶剂瓶前清洁溶剂库盖板!</span>
        </div>
        <div class="footer-right">
          <el-button @click="onCancel">取消</el-button>
          <el-button type="primary" :disabled="selectedCodes.length === 0" :loading="submitting" @click="onConfirm">确定</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Location } from '@element-plus/icons-vue'
import {
  batchUpdateResource,
  getResourceInfo,
  type BatchUpdateResourceItem,
  type BatchUpdateResourceTray,
} from '@/api/synthesis'
import { getModule } from '@/lib/dynamic-graph'
import { HIGHT_COLOR } from '@/lib/dynamic-graph/utils/consts'
import NTUStationGraph from '@/components/NTUStationGraph.vue'
import SlotConfigCard from './SlotConfigCard.vue'
import type { SelectedSlotConfig, TrayModelOption, WellInfo } from './types'
import {
  buildSlotConfig,
  isCountConsumableTray,
  isVolumeUnit,
  normalizeChemicalId,
} from '../StationDetail/buildTrayDetail'

interface Props {
  visible: boolean
  initialLayoutCode?: string
}
const props = withDefaults(defineProps<Props>(), { initialLayoutCode: '' })
const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'success'): void
}>()

const iconLocation = Location

const loading = ref(false)
const submitting = ref(false)
const emptyDesc = ref('请在左侧 3D 视图点击托盘或输入位置码')

const allTrayOptions = ref<TrayModelOption[]>([])
const trayOptions = computed(() => allTrayOptions.value)

// 已选编辑目标 layout_code 列表 (顺序保留, 用 ref 数组方便 v-for)
const selectedCodes = ref<string[]>([])
// 每个已选 layout_code 对应的 SelectedSlotConfig
const configMap = reactive<Record<string, SelectedSlotConfig>>({})
// 位置码输入框 v-model
const positionInput = ref('')
// NTUStationGraph 实例引用
const graphRef = ref<InstanceType<typeof NTUStationGraph> | null>(null)
// 工站资源全量列表, 仅在打开时拉一次
const allResources = ref<Array<Record<string, unknown>>>([])

watch(
  () => props.visible,
  (v) => {
    if (v) {
      // 每次打开重置 + 重新拉取资源全量
      resetState()
      void loadAndBuild()
    } else {
      resetState()
    }
  },
)

function resetState (): void {
  selectedCodes.value = []
  Object.keys(configMap).forEach((k) => { delete configMap[k] })
  positionInput.value = ''
  allResources.value = []
}

function loadTrayOptions (): void {
  // 与 ResourceAddDialog 同款 BaseTray 派生逻辑, 编辑模式不做侧别过滤
  try {
    const module = getModule()
    const all = module.BaseTray.getAllModels?.() || []
    const opts: TrayModelOption[] = []
    all.forEach((tray: any) => {
      const cfg = tray.config || {}
      const model = tray.model || cfg.model
      if (!model) { return }
      opts.push({
        model,
        name: cfg.name || model,
        row: Number(cfg.row) || 0,
        col: Number(cfg.col) || 0,
        childrenCount: Number(cfg.children_count) || (Number(cfg.row) * Number(cfg.col)) || 0,
        vesselModels: Array.isArray(cfg.vessel_models) ? cfg.vessel_models : [],
        noAddin: cfg.noAddin === true,
        defaultWithCap: typeof cfg.with_cap === 'boolean'
          ? cfg.with_cap
          : (typeof cfg.with_cap?.NTU === 'boolean' ? cfg.with_cap.NTU : true),
        defaultWithMagneton: cfg.isMagnetonTray === true || cfg.with_magneton === true,
        editSubstanceCreate: cfg.editSubstance?.create === true,
      })
    })
    allTrayOptions.value = opts
  } catch (err) {
    console.error('[ResourceEditDialog] loadTrayOptions failed:', err)
    allTrayOptions.value = []
  }
}

async function loadAndBuild (): Promise<void> {
  loading.value = true
  try {
    loadTrayOptions()
    await fetchAllResources()
    const initial = (props.initialLayoutCode || '').trim()
    if (initial) {
      // 初始 layout_code 由父组件透传 (如右键菜单), 自动加入选中
      tryAddSelection(initial)
    }
  } finally {
    loading.value = false
  }
}

async function fetchAllResources (): Promise<void> {
  try {
    const resp = await getResourceInfo({})
    const list = (resp?.resource_list as Array<Record<string, unknown>> | undefined) || []
    allResources.value = list
  } catch (err) {
    console.warn('[ResourceEditDialog] getResourceInfo failed:', err)
    allResources.value = []
    emptyDesc.value = '加载资源失败, 请稍后重试'
  }
}

// 解析 resource_list 为 SelectedSlotConfig, 失败时根据原因给中文提示
function buildConfigFromTarget (targetCode: string): SelectedSlotConfig | null {
  if (allResources.value.length === 0) {
    ElMessage.warning('工站资源为空, 无法编辑')
    return null
  }
  const result = buildSlotConfig(allResources.value, targetCode, allTrayOptions.value)
  if (result.ok === false) {
    if (result.reason === 'tray-not-found') {
      ElMessage.warning(`位置 ${targetCode} 无资源, 无法编辑`)
    } else if (result.reason === 'unknown-tray-model') {
      ElMessage.warning(`未识别托盘型号 ${result.trayModel || ''}`)
    }
    return null
  }
  return result.config
}

// 尝试把一个 layout_code 加入已选 (前置校验: 必须有资源 + 不重复)
function tryAddSelection (layoutCode: string): boolean {
  if (selectedCodes.value.includes(layoutCode)) { return false }
  // 3D 闸门: 槽位必须存在且有 tray
  const station: any = graphRef.value?.getStation?.()
  const slot: any = station?.slots?.[layoutCode]
  if (!slot || typeof slot.hasTray !== 'function' || slot.hasTray() !== true) {
    ElMessage({ message: `槽位 ${layoutCode} 无资源, 无法编辑`, type: 'warning' })
    return false
  }
  const cfg = buildConfigFromTarget(layoutCode)
  if (cfg === null) { return false }
  configMap[layoutCode] = reactive(cfg)
  selectedCodes.value = [...selectedCodes.value, layoutCode]
  setSlotHighlight(layoutCode, true)
  return true
}

function onClickTray (layoutCode: string): void {
  // 多选切换: 已选 → 取消; 未选 → 加入
  if (selectedCodes.value.includes(layoutCode)) {
    onDeselect(layoutCode)
  } else {
    tryAddSelection(layoutCode)
  }
}

function onPositionInputCommit (): void {
  const code = positionInput.value.trim()
  if (!code) { return }
  if (selectedCodes.value.includes(code)) {
    onDeselect(code)
  } else {
    tryAddSelection(code)
  }
  // 提交后清空输入框, 方便连续扫码 / 录入
  positionInput.value = ''
}

function onDeselect (layoutCode: string): void {
  if (!selectedCodes.value.includes(layoutCode)) { return }
  setSlotHighlight(layoutCode, false)
  selectedCodes.value = selectedCodes.value.filter((c) => c !== layoutCode)
  delete configMap[layoutCode]
}

function setSlotHighlight (layoutCode: string, on: boolean): void {
  const station: any = graphRef.value?.getStation?.()
  if (!station) { return }
  const slot: any = station.slots?.[layoutCode]
  if (!slot || typeof slot.setHighlight !== 'function') { return }
  // setHighlight 给 floor 染绿渐变, 与移出资源同款选中视觉, 不出现蓝点
  slot.setHighlight(on, on ? HIGHT_COLOR : undefined)
}

function onTrayQRChange (layoutCode: string, val: string): void {
  const cfg = configMap[layoutCode]
  if (cfg === undefined) { return }
  cfg.trayQRCode = val
}

function allowDisabledForConfig (cfg: SelectedSlotConfig | undefined): boolean {
  if (cfg === undefined) { return true }
  const trayOption = allTrayOptions.value.find((opt) => opt.model === cfg.trayModel)
  return isCountConsumableTray(trayOption) === false
}

function onWellsChange (layoutCode: string, wells: WellInfo[]): void {
  const cfg = configMap[layoutCode]
  if (cfg === undefined) { return }
  cfg.wells = wells
}

function onCancel (): void {
  emit('update:visible', false)
}

// 组装单托盘 BatchUpdateResource payload
function buildBatchUpdateTray (cfg: SelectedSlotConfig): BatchUpdateResourceTray {
  const trayOption = allTrayOptions.value.find((opt) => opt.model === cfg.trayModel)
  const isCountConsumable = isCountConsumableTray(trayOption)
  const resourceList: BatchUpdateResourceItem[] = [
    {
      layout_code: `${cfg.layoutCode}:-1`,
      slot_index: -1,
      with_cap: false,
      resource_type: cfg.trayModel,
    },
  ]

  cfg.wells
    .filter((w) => isCountConsumable ? w.state === 'filled' : w.state !== 'empty')
    .forEach((w) => {
      const resourceType = w.resourceType || trayOption?.vesselModels[0] || ''
      if (resourceType === '') {
        throw new Error(`托盘 ${cfg.layoutCode} 的 ${w.colLabel}${w.rowLabel} 缺少孔位资源类型`)
      }

      if (isCountConsumable) {
        const item: BatchUpdateResourceItem = {
          cur_weight: 0,
          unit: 'mg',
          substance: '',
          chemical_id: null,
          resource_type: resourceType,
          with_cap: false,
          with_magneton: false,
          layout_code: `${cfg.layoutCode}:${w.slotIndex}`,
          content: '',
        }
        resourceList.push(item)
        return
      }

      const unit = (w.unit || '').trim() || 'mg'
      const amount = w.amount !== null && w.amount !== undefined
        ? w.amount
        : null
      const item: BatchUpdateResourceItem = {
        layout_code: `${cfg.layoutCode}:${w.slotIndex}`,
        resource_type: resourceType,
        substance: w.substance || '',
        chemical_id: normalizeChemicalId(w.chemical_id),
        with_cap: w.with_cap,
        with_magneton: w.with_magneton,
        unit,
        content: w.content || '',
      }

      if (amount !== null) {
        if (isVolumeUnit(unit)) {
          item.cur_volume = amount
        } else {
          item.cur_weight = amount
        }
      }
      if (w.state === 'disabled') { item.status = 3 }
      resourceList.push(item)
    })

  return {
    remark: cfg.remark || '',
    tray_layout_code: cfg.layoutCode,
    resource_list: resourceList,
  }
}

async function onConfirm (): Promise<void> {
  if (selectedCodes.value.length === 0) {
    ElMessage.warning('请先选择有资源的位置')
    return
  }
  submitting.value = true
  try {
    // 按当前选择顺序组装 resource_req_list, 由 BatchUpdateResource 一次提交.
    const resourceReqList: BatchUpdateResourceTray[] = []
    for (const code of selectedCodes.value) {
      const cfg = configMap[code]
      if (cfg === undefined) { continue }
      resourceReqList.push(buildBatchUpdateTray(cfg))
    }
    await batchUpdateResource({ resource_req_list: resourceReqList })
    ElMessage.success('编辑资源成功')
    emit('success')
    emit('update:visible', false)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    ElMessage.error(`编辑资源失败: ${msg}`)
  } finally {
    submitting.value = false
  }
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
  background: #fff;
  padding: 8px;
  border-radius: 6px;
  overflow: hidden;
}
.two-col {
  display: grid;
  /* 左右各占 1/2, 让右栏 SlotConfigCard 能完整渲染 (托盘缩略 + 网格 + 物质表) */
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  height: 100%;
}
.col {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}
.step-title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  border-bottom: 1px solid #f0f2f5;
  background: #fff;
}
.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ebea1;
}
.col-inner {
  flex: 1 1 auto;
  min-height: 0;
  padding: 12px;
}
.col-inner.preview-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}
.col-inner.preview-inner :deep(.ntu-station-graph) {
  flex: 1 1 auto;
  min-height: 0;
}
.col-inner.scroll {
  overflow-y: auto;
}
.position-input-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.position-input-bar :deep(.el-input) {
  flex: 0 0 240px;
  min-width: 0;
}
.tag-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1 1 auto;
  min-width: 0;
}
.dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.footer-left {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #f56c6c;
  font-size: 13px;
}
.warning-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f56c6c;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
}
.footer-right {
  display: flex;
  gap: 8px;
}
</style>
