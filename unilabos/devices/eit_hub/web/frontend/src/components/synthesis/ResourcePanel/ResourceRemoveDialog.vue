<template>
  <!--
    功能:
      删除资源对话框. 1:1 复刻 web_code ResourceAddV3.vue 在 op=TrayOperate.out 模式下的形态:
        - 左栏 资源视图预览: 主页同款 NTUStationGraph (与 SynthesisView 视觉一致), 点击有资源的槽位将其加入待移出列表并染绿
        - 右栏 待移出资源的槽位: el-table, 列含 槽位条码 / 托盘条码 / 托盘类型 / 操作 (移除)
      底部 取消 / 确定. 提交时按 web_code removeResourceBatch 逻辑组装 batchOutTray payload.
    事件:
      success: 移出成功后通知父组件刷新主 3D 视图与库存.
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
      <div class="dialog-title">删除资源</div>
    </template>
    <div class="dialog-body" v-loading="loading">
      <div class="two-col">
        <div class="col col-left">
          <div class="step-title"><span class="step-dot"></span>资源视图预览</div>
          <div class="col-inner preview-inner">
            <NTUStationGraph
              ref="graphRef"
              :margin="24"
              :auto-select-on-click="false"
              :on-click-tray="onClickTray"
            />
          </div>
        </div>
        <div class="col col-right">
          <div class="step-title">
            <span class="step-dot"></span>
            <span>待移出资源的槽位</span>
            <span class="step-hint">(注: 确定后可实时关注待出料列表和资源视图, 及时将资源从交换仓货架TB位取走)</span>
          </div>
          <div class="col-inner">
            <el-table
              :data="selectedRows"
              :header-cell-style="{ background: '#EFF0F5', color: '#828AB0' }"
              empty-text=" "
              style="width: 100%"
              height="100%"
            >
              <el-table-column prop="layout_code" label="槽位条码" />
              <el-table-column label="托盘条码">
                <template #default="{ row }">{{ row.tray_QR_code || '' }}</template>
              </el-table-column>
              <el-table-column label="托盘类型">
                <template #default="{ row }">{{ row.resource_type || '' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button type="danger" link @click="onDeselect(row.layout_code)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
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
import { batchOutTray, getResourceInfo } from '@/api/synthesis'
import NTUStationGraph from '@/components/NTUStationGraph.vue'
import { HIGHT_COLOR } from '@/lib/dynamic-graph/utils/consts'

interface ResourceRow {
  layout_code: string
  resource_type?: string
  tray_QR_code?: string
  [key: string]: unknown
}

interface Props {
  visible: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'success'): void
}>()

const loading = ref(false)
const submitting = ref(false)

// NTUStationGraph 的实例引用, 通过 getStation() 拿到底层 station 操作槽位高亮
const graphRef = ref<InstanceType<typeof NTUStationGraph> | null>(null)

// 当前工站全部资源 (打开弹窗时拉取一次), key 为顶层托盘 layout_code
const resourceMap = reactive<Record<string, ResourceRow>>({})
// 已选 layout_code 集合
const selectedSet = reactive(new Set<string>())
const selectedCodes = computed(() => Array.from(selectedSet))
// 右栏表格数据: 优先用 resourceMap (来自 getResourceInfo); 缺失时从 station.slots[code].tray.resource 兜底,
// 让 W-1-x 这种 getResourceInfo({}) 漏拉的位置也能填上 tray_QR_code / resource_type.
const selectedRows = computed<ResourceRow[]>(() =>
  selectedCodes.value.map((code) => {
    const fromMap = resourceMap[code]
    if (fromMap !== undefined && (fromMap.resource_type !== undefined || fromMap.tray_QR_code !== undefined)) {
      return fromMap
    }
    const station: any = graphRef.value?.getStation?.()
    const slot: any = station?.slots?.[code]
    const tray: any = slot?.tray
    if (tray !== undefined && tray !== null) {
      return {
        layout_code: code,
        resource_type: tray.resource?.resource_type || tray.model || undefined,
        tray_QR_code: tray.resource?.tray_QR_code || undefined,
      }
    }
    return { layout_code: code }
  }),
)

// 关闭弹窗时清理状态
function resetState (): void {
  Object.keys(resourceMap).forEach((k) => { delete resourceMap[k] })
  selectedSet.clear()
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      // 每次打开重置状态. NTUStationGraph 因为父级 destroy-on-close 会自动重建, 不需手动清理高亮.
      resetState()
      void loadResources()
    }
  },
)

async function loadResources (): Promise<void> {
  loading.value = true
  try {
    const resp = await getResourceInfo({})
    const list = (resp?.resource_list as ResourceRow[] | undefined) || []
    // 设备 /api/GetResourceInfo 返回的 layout_code 是子层级形态:
    //   - "N-4:-1"  托盘存在标记 (slot_index = -1, 携带 tray_QR_code 与托盘 resource_type)
    //   - "N-4:0"   孔位条目     (slot_index >= 0, resource_type 是 vessel 模型而非托盘)
    //   - "N-4"     纯顶层 (空托盘场景)
    // 顶层托盘 layout_code 由前端从 split(':')[0] 派生, 与 web_code resource.ts:76-113 一致.
    list.forEach((item) => {
      const code = item.layout_code
      if (typeof code !== 'string' || code === '') { return }
      const colonIdx = code.indexOf(':')
      const topCode = colonIdx === -1 ? code : code.slice(0, colonIdx)
      const isTrayLevel = colonIdx === -1 || Number(code.slice(colonIdx + 1)) === -1
      const existing = resourceMap[topCode]
      if (existing === undefined) {
        // 第一次遇到该顶层 code, 建占位
        resourceMap[topCode] = {
          layout_code: topCode,
          resource_type: isTrayLevel ? (item.resource_type as string | undefined) : undefined,
          tray_QR_code: isTrayLevel ? (item.tray_QR_code as string | undefined) : undefined,
        }
        return
      }
      // 已有占位, 仅在拿到托盘级条目时补全 (孔位级的 resource_type 是 vessel 模型, 不能用)
      if (isTrayLevel) {
        if (existing.resource_type === undefined && item.resource_type) {
          existing.resource_type = item.resource_type as string
        }
        if (existing.tray_QR_code === undefined && item.tray_QR_code) {
          existing.tray_QR_code = item.tray_QR_code as string
        }
      }
    })
  } catch (err) {
    console.warn('[ResourceRemoveDialog] getResourceInfo failed:', err)
  } finally {
    loading.value = false
  }
}

// NTUStationGraph 透传过来的点击事件, 这里完成"有资源放行 + 染绿; 无资源拒绝 + 提示"的闸门
// 闸门用 station.slots[code].hasTray() 判断, 直接反映视图渲染中的真实状态;
// 不依赖 resourceMap (因为 getResourceInfo({}) 与 useStationGraph 内部 { roll: 'normal' } 拉取的资源子集可能不同, 会漏 W-1-x 上料货架).
function onClickTray (layoutCode: string): void {
  if (selectedSet.has(layoutCode)) {
    selectedSet.delete(layoutCode)
    setSlotHighlight(layoutCode, false)
    return
  }
  const station: any = graphRef.value?.getStation?.()
  const slot: any = station?.slots?.[layoutCode]
  if (slot === undefined || slot === null || typeof slot.hasTray !== 'function' || slot.hasTray() !== true) {
    ElMessage({
      message: `槽位 ${layoutCode} 无资源, 无法移出`,
      type: 'warning',
      customClass: 'msg-above-dialog',
    })
    return
  }
  selectedSet.add(layoutCode)
  setSlotHighlight(layoutCode, true)
}

// 右表"移除"列触发: 把这一行从已选列表去除, 同步取消 3D 视图高亮
function onDeselect (layoutCode: string): void {
  if (!selectedSet.has(layoutCode)) { return }
  selectedSet.delete(layoutCode)
  setSlotHighlight(layoutCode, false)
}

function setSlotHighlight (layoutCode: string, on: boolean): void {
  const station: any = graphRef.value?.getStation?.()
  if (!station) { return }
  const slot = station.slots?.[layoutCode]
  if (!slot || typeof slot.setHighlight !== 'function') { return }
  // setHighlight 给 floor 染绿渐变, 不展开 z0/z1 SVG, 与 web_code 选中视觉一致且无蓝点
  slot.setHighlight(on, on ? HIGHT_COLOR : undefined)
}

async function onConfirm (): Promise<void> {
  if (selectedSet.size === 0) {
    ElMessage({
      message: '请选择移出资源的位置',
      type: 'warning',
      customClass: 'msg-above-dialog',
    })
    return
  }
  const layout_list = selectedRows.value.map((row) => ({
    layout_code: row.layout_code,
    resource_type: row.resource_type,
  }))
  submitting.value = true
  try {
    await batchOutTray({ layout_list, move_type: 'main_out' })
    ElMessage({
      message: '移除资源操作成功, 实际移动情况请以资源视图显示为准',
      type: 'success',
      customClass: 'msg-above-dialog',
    })
    emit('success')
    emit('update:visible', false)
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '移出失败'
    ElMessage({
      message: `移出失败: ${detail}`,
      type: 'error',
      customClass: 'msg-above-dialog',
    })
  } finally {
    submitting.value = false
  }
}

function onCancel (): void {
  emit('update:visible', false)
}

defineExpose({ resetState })
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
  /* 左栏 3D 视图占 2/3, 右栏待移出表格占 1/3 */
  grid-template-columns: 2fr 1fr;
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
.step-hint {
  font-size: 12px;
  font-weight: 400;
  color: #ff1212;
  margin-left: 8px;
}
.step-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0dbf75;
  flex: 0 0 auto;
}
.preview-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px;
  overflow: auto;
}
.col-inner {
  flex: 1 1 auto;
  min-height: 0;
  background: #fff;
  border-radius: 6px;
  padding: 10px;
  overflow: hidden;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

<style>
/* 全局: 让 ElMessage 浮在 dialog (z-index=5000) 之上, 避免被遮挡看不见 */
.msg-above-dialog {
  z-index: 6000 !important;
}
</style>
