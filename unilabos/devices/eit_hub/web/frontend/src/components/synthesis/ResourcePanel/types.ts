/**
 * 功能:
 *   ResourcePanel 录入资源对话框共用类型.
 */

// 一个孔位的状态: 未放入 / 已放入 / 禁用 (与 web_code TraySlotsV2 三态一致)
export type WellState = 'empty' | 'filled' | 'disabled'

// 单个孔位的渲染数据 + 物质明细 (web_code 截图所示极简列集合)
// 仅保留: 孔位坐标 + 状态 + 介质内物质 (chemical_id + substance) + 物质的量 (amount + unit) + 是否带盖
// 高级字段 (with_magneton/QR_code/material_batch_number/resource_type) 本期不暴露
export interface WellInfo {
  slotIndex: number
  rowIndex: number
  colIndex: number
  rowLabel: string
  colLabel: string
  state: WellState
  substance: string
  unit: string
  amount: number | null
  chemical_id: string
  with_cap: boolean
  with_magneton: boolean
}

// 托盘型号下拉选项, 由 BaseTray.getAllModels() 派生
export interface TrayModelOption {
  model: string
  name: string
  row: number
  col: number
  childrenCount: number
  vesselModels: string[]
  noAddin: boolean
  defaultWithCap: boolean
  defaultWithMagneton: boolean
  // 是否允许编辑物质 (来自 config.editSubstance.create), 区分试剂托盘与物料/Tip 托盘:
  // true  → 试剂托盘 (默认空盘, 显示 VesselEditor 让用户填入物质)
  // false → 物料/Tip 托盘 (默认满盘, 不显示物质表)
  editSubstanceCreate: boolean
}

// 选中槽位上下文, 在对话框内为每个 layout_code 维护一份配置
export interface SelectedSlotConfig {
  layoutCode: string
  trayModel: string
  trayQRCode: string
  remark: string
  // wells 长度 = row * col, 索引即 slot_index
  wells: WellInfo[]
}
