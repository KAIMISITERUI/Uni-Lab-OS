/**
 * 功能:
 *   将 GetResourceInfo 返回的扁平 resource_list 解析为浮卡/资源编辑共用的结构.
 *   逻辑与 ResourceEditDialog.vue 中原 buildConfigFromTarget 一致, 抽出为纯函数:
 *     - buildSlotConfig: 输入 resource_list + targetCode + trayOptions, 输出 SelectedSlotConfig 或失败原因
 *     - buildTrayDetail: 在 buildSlotConfig 之上, 根据 editSubstanceCreate 区分耗材/试剂, 给浮卡使用
 *   不含任何 UI 副作用 (ElMessage 等), 调用方按需提示.
 */
import type { SelectedSlotConfig, TrayModelOption, WellInfo, WellState } from '../ResourcePanel/types'

export type RawResourceItem = Record<string, unknown>

export type SlotConfigError = 'tray-not-found' | 'unknown-tray-model'

export type SlotConfigResult =
  | { ok: true; config: SelectedSlotConfig; trayOption: TrayModelOption }
  | { ok: false; reason: SlotConfigError; trayModel?: string }

// 单位识别: 容量单位 (mL/L/μL/nL...) 与质量单位 (mg/g/kg/μg/ng) 二分类
export function isVolumeUnit (unit: string): boolean {
  const normalized = unit.trim().toLowerCase()
  return ['ml', 'l', 'ul', 'μl', 'µl', 'nl'].includes(normalized)
}

// 是否为计数型耗材托盘 (Tip / 反应试管 / 磁子 / 盖子等):
//   editSubstanceCreate=false 且有 vessel_models, 用于区分耗材计数 vs 试剂量
export function isCountConsumableTray (trayOption: TrayModelOption | undefined): boolean {
  if (trayOption === undefined) {
    return false
  }
  return trayOption.editSubstanceCreate === false && trayOption.vesselModels.length > 0
}

// chemical_id 规范化: 数字字符串 → 数字, 非数字字符串保留原样, 空串 → null
export function normalizeChemicalId (chemicalId: string): number | string | null {
  const trimmed = chemicalId.trim()
  if (trimmed === '') {
    return null
  }
  const numericId = Number(trimmed)
  return Number.isFinite(numericId) ? numericId : trimmed
}

// 从 well 条目中提取当前量 + 单位:
//   1) unit 字段权威: mg/g/kg/μg/ng → weight 维度, mL/L/μL/nL → volume 维度
//   2) 0 是合法当前量 (耗尽), 不能被回落覆盖; 回落仅在 cur_* 为 undefined/null/'' 时发生
export function pickAmountAndUnit (item: RawResourceItem): { amount: number | null; unit: string } {
  const rawUnit = typeof item.unit === 'string' ? item.unit.trim() : ''
  const isVolume = /^(?:[mμuµn]?l)$/i.test(rawUnit)
  const isWeight = /^(?:[mμuµn]?g|kg)$/i.test(rawUnit)
  const kind: 'weight' | 'volume' | 'unknown' =
    isVolume ? 'volume' : isWeight ? 'weight' : 'unknown'

  const toNum = (v: unknown): number | null => {
    if (v === undefined || v === null || v === '') {
      return null
    }
    const n = typeof v === 'number' ? v : Number(v)
    return Number.isFinite(n) ? n : null
  }

  let amount: number | null = null
  if (kind === 'weight') {
    amount = toNum(item.cur_weight)
    if (amount === null) {
      amount = toNum(item.available_weight)
    }
    if (amount === null) {
      amount = toNum(item.initial_weight)
    }
  } else if (kind === 'volume') {
    amount = toNum(item.cur_volume)
    if (amount === null) {
      amount = toNum(item.available_volume)
    }
    if (amount === null) {
      amount = toNum(item.initial_volume)
    }
  } else {
    const w = toNum(item.cur_weight)
    const v = toNum(item.cur_volume)
    amount = w !== null ? w : v
    if (amount === null) {
      amount = toNum(item.amount)
    }
  }

  const unit = rawUnit || (kind === 'volume' ? 'mL' : 'mg')
  return { amount, unit }
}

// 把扁平 resource_list 中属于 targetCode 的条目组装成 SelectedSlotConfig
// 失败原因:
//   tray-not-found     工站资源里没有 targetCode 对应的托盘级条目
//   unknown-tray-model 找到了托盘但 trayOptions 里没注册该型号
export function buildSlotConfig (
  resourceList: RawResourceItem[],
  targetCode: string,
  trayOptions: TrayModelOption[]
): SlotConfigResult {
  // 拆分托盘级 (slot_index === -1 或不带冒号) 与 孔位级 (slot_index >= 0)
  let trayEntry: RawResourceItem | null = null
  const wellEntries: RawResourceItem[] = []
  resourceList.forEach((item) => {
    const code = String(item.layout_code || '')
    if (code === '') {
      return
    }
    const colonIdx = code.indexOf(':')
    const topCode = colonIdx === -1 ? code : code.slice(0, colonIdx)
    if (topCode !== targetCode) {
      return
    }
    const isTrayLevel = colonIdx === -1 || Number(code.slice(colonIdx + 1)) === -1
    if (isTrayLevel) {
      trayEntry = item
    } else {
      wellEntries.push(item)
    }
  })

  if (trayEntry === null) {
    return { ok: false, reason: 'tray-not-found' }
  }

  const trayModel = String((trayEntry as RawResourceItem).resource_type || '')
  const opt = trayOptions.find((o) => o.model === trayModel)
  if (!opt) {
    return { ok: false, reason: 'unknown-tray-model', trayModel }
  }

  const isCountConsumable = isCountConsumableTray(opt)
  const wells: WellInfo[] = []
  for (let c = 1; c <= opt.col; c++) {
    for (let r = 1; r <= opt.row; r++) {
      wells.push({
        slotIndex: (c - 1) * opt.row + (r - 1),
        rowIndex: r,
        colIndex: c,
        rowLabel: String(r),
        colLabel: String.fromCharCode(64 + c),
        state: 'empty',
        substance: '',
        unit: 'mg',
        amount: null,
        chemical_id: '',
        with_cap: opt.defaultWithCap,
        with_magneton: opt.defaultWithMagneton,
        resourceType: opt.vesselModels[0] || '',
        content: '',
      })
    }
  }
  wellEntries.forEach((item) => {
    const code = String(item.layout_code || '')
    const idx = Number(code.slice(code.indexOf(':') + 1))
    if (!Number.isFinite(idx) || idx < 0 || idx >= wells.length) {
      return
    }
    const status = Number(item.status)
    let nextState: WellState = 'filled'
    if (status === 3) {
      nextState = isCountConsumable ? 'empty' : 'disabled'
    } else if (status === 2) {
      nextState = 'empty'
    }
    const { amount, unit } = pickAmountAndUnit(item)
    wells[idx] = {
      ...wells[idx],
      state: nextState,
      substance: String(item.substance || ''),
      unit,
      amount,
      chemical_id: item.chemical_id !== undefined && item.chemical_id !== null ? String(item.chemical_id) : '',
      with_cap: typeof item.with_cap === 'boolean' ? item.with_cap : wells[idx].with_cap,
      with_magneton: item.with_magneton === true,
      resourceType: String(item.resource_type || wells[idx].resourceType || ''),
      content: item.content !== undefined && item.content !== null ? String(item.content) : '',
    }
  })

  const config: SelectedSlotConfig = {
    layoutCode: targetCode,
    trayModel,
    trayQRCode: String((trayEntry as RawResourceItem).tray_QR_code || ''),
    remark: '',
    wells,
  }
  return { ok: true, config, trayOption: opt }
}

// 浮卡详情结构
export interface ConsumableTrayDetail {
  kind: 'consumable'
  layoutCode: string
  trayModel: string
  name: string
  filledCount: number
  capacity: number
}

export interface ReagentTrayDetail {
  kind: 'reagent'
  layoutCode: string
  trayModel: string
  name: string
  row: number
  col: number
  wells: WellInfo[]
}

export type TrayDetail = ConsumableTrayDetail | ReagentTrayDetail

// 浮卡入口: 解析 resource_list, 区分耗材/试剂, 失败或空托盘统一返回 null
export function buildTrayDetail (
  resourceList: RawResourceItem[],
  targetCode: string,
  trayOptions: TrayModelOption[]
): TrayDetail | null {
  const result = buildSlotConfig(resourceList, targetCode, trayOptions)
  if (!result.ok) {
    return null
  }
  const { config, trayOption } = result
  const capacity = trayOption.childrenCount > 0
    ? trayOption.childrenCount
    : trayOption.row * trayOption.col

  if (isCountConsumableTray(trayOption)) {
    const filledCount = config.wells.filter((w) => w.state === 'filled').length
    return {
      kind: 'consumable',
      layoutCode: targetCode,
      trayModel: config.trayModel,
      name: trayOption.name,
      filledCount,
      capacity,
    }
  }
  return {
    kind: 'reagent',
    layoutCode: targetCode,
    trayModel: config.trayModel,
    name: trayOption.name,
    row: trayOption.row,
    col: trayOption.col,
    wells: config.wells,
  }
}
