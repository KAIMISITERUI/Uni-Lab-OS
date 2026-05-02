<template>
  <!--
    功能:
      点击托盘后弹出的一级浮卡, 通过 Teleport 挂到 body, 绝对定位到点击坐标.
      根据 detail.kind 渲染两种内容:
        - consumable: 名称 + 已放入数量 + 位置码
        - reagent: 名称 + ReagentSlotMap 盘位图 + 位置码
                   点击 filled 孔位时弹出二级 Popover, 显示该试剂的结构式 + 名称 + 剩余量
      点击浮卡外部关闭, 点击关闭按钮关闭, 父组件可通过 v-if 控制可见性.
  -->
  <Teleport to="body">
    <div
      ref="popoverRef"
      class="tray-detail-popover"
      :class="{ 'tray-detail-popover-mobile': isMobile === true }"
      :style="positionStyle"
      @mousedown.stop
    >
      <div class="popover-header">
        <span class="popover-title" :title="detail.name">{{ detail.name }}</span>
        <span class="popover-close" @click="emit('close')">×</span>
      </div>
      <div class="popover-body">
        <template v-if="detail.kind === 'consumable'">
          <div class="info-row">
            <span class="info-label">已放入</span>
            <span class="info-value">{{ detail.filledCount }} / {{ detail.capacity }}</span>
          </div>
        </template>
        <template v-else>
          <ReagentSlotMap
            :row="detail.row"
            :col="detail.col"
            :wells="detail.wells"
            :selected-slot-index="selectedSlot?.slotIndex ?? null"
            @select="onSlotSelect"
          />
        </template>
      </div>
      <div class="popover-footer">
        <span class="info-label">位置码</span>
        <span class="info-value mono">{{ detail.layoutCode }}</span>
      </div>

      <!--
        二级 Popover: 试剂模式下点击 filled 孔位时显示.
        采用 virtual-ref 锚定到孔位 DOM, manual 触发以便外部点击关闭.
      -->
      <el-popover
        v-if="detail.kind === 'reagent'"
        :virtual-ref="selectedSlot?.el"
        virtual-triggering
        :visible="selectedSlot !== null"
        :placement="isMobile === true ? 'bottom' : 'right'"
        trigger="manual"
        :width="isMobile === true ? 240 : 196"
        :show-arrow="isMobile === false"
        popper-class="tray-detail-reagent-popper"
        :popper-style="{ zIndex: 4600 }"
      >
        <div v-if="selectedSlot !== null" class="reagent-card">
          <div class="reagent-row">
            <span class="info-label">名称</span>
            <span class="info-value">{{ selectedSlot.well.substance || '(未填写)' }}</span>
          </div>
          <div class="reagent-row">
            <span class="info-label">剩余</span>
            <span class="info-value">{{ formatAmount(selectedSlot.well) }}</span>
          </div>
          <div class="reagent-structure">
            <StructurePreview :smiles="currentSmiles" :width="168" :height="126" />
          </div>
        </div>
      </el-popover>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * 功能:
 *   托盘详情浮卡. 自定位到点击坐标, 自动避免溢出右/下边界.
 *   reagent 模式下额外管理一个二级 el-popover, 用于展示具体孔位试剂详情.
 * 缓存:
 *   chemical_id → smiles 在组件内 Map 缓存, 切换孔位时不重复请求.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElPopover } from 'element-plus'
import StructurePreview from '@/components/StructurePreview.vue'
import { getChemicalBySubstance } from '@/api/chemicals'
import { useViewportMode } from '@/composables/useViewportMode'
import type { TrayDetail } from './buildTrayDetail'
import type { WellInfo } from '../ResourcePanel/types'
import ReagentSlotMap from './ReagentSlotMap.vue'

interface Props {
  detail: TrayDetail
  // 锚点为 NTUStationGraph 容器内坐标, 已在父组件转换为 viewport (clientX/clientY)
  anchor: { x: number; y: number }
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'close'): void
}>()

const popoverRef = ref<HTMLDivElement | null>(null)
const positionStyle = ref<Record<string, string>>({ left: '0px', top: '0px', visibility: 'hidden' })
const { isMobile } = useViewportMode()

interface SelectedSlot {
  slotIndex: number
  well: WellInfo
  el: HTMLElement
}
const selectedSlot = ref<SelectedSlot | null>(null)

// substance → smiles 缓存, 避免切换孔位重复请求
const smilesCache = new Map<string, string>()
const currentSmiles = ref<string>('')

const POPOVER_WIDTH_FALLBACK = 280
const POPOVER_HEIGHT_FALLBACK = 280
const ANCHOR_OFFSET = 12

function applyPosition (): void {
  // 手机端: 直接固定为底部 sheet, 不再按 anchor 计算 (CSS 在 .tray-detail-popover-mobile 上接管)
  if (isMobile.value === true) {
    positionStyle.value = { visibility: 'visible' }
    return
  }
  // 桌面端: 默认锚点右下方; 若超出 viewport 则向左/上翻转
  const dom = popoverRef.value
  const w = dom?.offsetWidth || POPOVER_WIDTH_FALLBACK
  const h = dom?.offsetHeight || POPOVER_HEIGHT_FALLBACK
  const vw = window.innerWidth
  const vh = window.innerHeight

  let left = props.anchor.x + ANCHOR_OFFSET
  let top = props.anchor.y + ANCHOR_OFFSET
  if (left + w > vw - 8) {
    left = Math.max(8, props.anchor.x - w - ANCHOR_OFFSET)
  }
  if (top + h > vh - 8) {
    top = Math.max(8, props.anchor.y - h - ANCHOR_OFFSET)
  }
  positionStyle.value = { left: `${left}px`, top: `${top}px`, visibility: 'visible' }
}

function onWindowMouseDown (event: MouseEvent): void {
  // 浮卡外部 (含二级 popover 外部) 点击 → 关闭整张浮卡
  const target = event.target as Node | null
  if (target === null) {
    return
  }
  if (popoverRef.value !== null && popoverRef.value.contains(target) === true) {
    return
  }
  // el-popover 内容 teleport 到 body, 用类名命中
  const popperEl = (target as HTMLElement).closest?.('.tray-detail-reagent-popper')
  if (popperEl !== null && popperEl !== undefined) {
    return
  }
  emit('close')
}

function onWindowKeydown (event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close')
  }
}

async function loadSmilesForCurrent (): Promise<void> {
  const slot = selectedSlot.value
  if (slot === null) {
    currentSmiles.value = ''
    return
  }
  // 仅按 substance 名称查 (孔位条目的 chemical_id 与化学品库主键不一致, 易拿到错对应记录)
  const substance = slot.well.substance
  if (substance === '') {
    currentSmiles.value = ''
    return
  }
  const cached = smilesCache.get(substance)
  if (cached !== undefined) {
    currentSmiles.value = cached
    return
  }
  // 占位空 smiles, StructurePreview 会显示加载中直到拿到数据
  currentSmiles.value = ''
  let smiles = ''
  try {
    const chem = await getChemicalBySubstance(substance)
    smiles = chem?.smiles ?? ''
  } catch (err) {
    console.warn('[TrayDetailPopover] getChemicalBySubstance failed:', err)
  }
  smilesCache.set(substance, smiles)
  // 检查请求返回时用户是否仍停在同一孔位 (避免快速切换覆盖)
  if (selectedSlot.value !== null && selectedSlot.value.slotIndex === slot.slotIndex) {
    currentSmiles.value = smiles
  }
}

function onSlotSelect (payload: SelectedSlot): void {
  // 同孔位再次点击 → 关闭二级 popover
  if (selectedSlot.value !== null && selectedSlot.value.slotIndex === payload.slotIndex) {
    selectedSlot.value = null
    return
  }
  selectedSlot.value = payload
}

function formatAmount (well: WellInfo): string {
  if (well.amount === null || well.amount === undefined) {
    return `- ${well.unit || ''}`.trim()
  }
  return `${well.amount} ${well.unit || ''}`.trim()
}

watch(
  () => selectedSlot.value?.slotIndex,
  () => {
    void loadSmilesForCurrent()
  },
)

watch(
  () => props.detail.layoutCode,
  () => {
    // 切换托盘时重置二级选中
    selectedSlot.value = null
  },
)

watch(
  () => props.anchor,
  () => {
    // 锚点变化 (切到新托盘) 重新定位
    void requestRepositionNextTick()
  },
)

watch(
  () => props.detail,
  () => {
    void requestRepositionNextTick()
  },
  { deep: true },
)

async function requestRepositionNextTick (): Promise<void> {
  // 等待 DOM 更新完毕再读 offsetWidth
  await Promise.resolve()
  applyPosition()
}

onMounted(() => {
  void requestRepositionNextTick()
  window.addEventListener('mousedown', onWindowMouseDown, true)
  window.addEventListener('keydown', onWindowKeydown, true)
  window.addEventListener('resize', applyPosition)
})

onBeforeUnmount(() => {
  window.removeEventListener('mousedown', onWindowMouseDown, true)
  window.removeEventListener('keydown', onWindowKeydown, true)
  window.removeEventListener('resize', applyPosition)
})
</script>

<style scoped>
.tray-detail-popover {
  position: fixed;
  z-index: 4500;
  min-width: 220px;
  max-width: 360px;
  background: #fff;
  border: 1px solid #e0e6f0;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 0;
  font-size: 13px;
  color: #303133;
}
.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
  border-radius: 8px 8px 0 0;
}
.popover-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.popover-close {
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
  color: #909399;
  user-select: none;
  padding: 0 2px;
}
.popover-close:hover {
  color: #303133;
}
.popover-body {
  padding: 12px;
}
.popover-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-top: 1px solid #f0f2f5;
  background: #fafbfc;
  border-radius: 0 0 8px 8px;
}
.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.info-label {
  color: #909399;
  font-size: 12px;
}
.info-value {
  color: #303133;
  font-weight: 600;
}
.info-value.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 500;
  font-size: 12px;
}
.reagent-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.reagent-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
}
.reagent-row .info-label {
  font-size: 10px;
}
.reagent-row .info-value {
  font-size: 11px;
}
.reagent-structure {
  display: flex;
  justify-content: center;
  margin-top: 2px;
}

/* 手机端: 底部上拉 sheet, 覆盖桌面端的 anchor 跟随定位 */
@media (max-width: 767.98px) {
  .tray-detail-popover-mobile {
    position: fixed;
    inset: auto 0 0 0;
    left: 0 !important;
    right: 0 !important;
    top: auto !important;
    bottom: 0;
    width: 100vw;
    max-width: 100vw;
    min-width: 0;
    max-height: 70dvh;
    overflow: auto;
    border: 0;
    border-top: 1px solid #e0e6f0;
    border-radius: 12px 12px 0 0;
    padding-bottom: env(safe-area-inset-bottom);
    box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.16);
  }
}
</style>
