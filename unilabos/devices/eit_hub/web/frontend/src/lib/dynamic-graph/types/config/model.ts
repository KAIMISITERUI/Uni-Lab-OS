import { TrayConfig, VesselConfig } from 'Types/model/tray'

// 工站配置信息
export interface ModelStationItem {
  model: string;
  [propName: string]: any;
}

// 位置配置信息
export interface ModelLayoutCode {
  // 该位置可放置的资源类型: 进料、移入
  // key表示槽位的前缀或完整码 value表示该槽位可放置的资源类型(空数组表示任意类型都不可放置，[ "*" ]表示任意类型都可放置)
  // 如果某个位置没有配置在in中，则表示该位置可放入任意型号
  in?: Record<string, Array<string>>;
  // 该位置可出料的资源型号
  out?: Record<string, Array<string>>;
  // 该位置移出(移动资源时)的资源型号
  moveOut?: Record<string, Array<string>>;
  // 该位置移入(移动资源时)的资源型号
  moveIn?: Record<string, Array<string>>;
  [propName: string]: any;
}

export interface ModelConfigDef {
  station?: Record<string, ModelStationItem>;
  tray?: Record<string, TrayConfig>; // key为托盘型号
  vessel?: Record<string, VesselConfig>
  layout_code?: Record<string, ModelLayoutCode>;
}
