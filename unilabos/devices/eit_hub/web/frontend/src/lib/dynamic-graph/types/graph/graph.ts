import type { ZRenderType } from 'zrender'

export enum RulerType {
  normal = '',
  small = 'small',
  medium = 'medium',
  large = 'large'
}

export interface RecordItem {
  x: number;
  y: number;
  width: number;
  height: number;
  [propName: string]: any;
}

export interface Recorder {
  anchors: Record<string, RecordItem>;
  rulers: Record<string, RecordItem>;
}

export interface GraphCallback {
  clickTray: (layout_code: string, x: number, y: number) => void;
  // 右键菜单回调, 在 zrender contextmenu 事件命中槽位时触发
  // x/y 为相对画布的偏移坐标, 由调用方决定如何映射为屏幕坐标
  contextMenuTray?: (layout_code: string, x: number, y: number) => void;
}

export type _ZRenderType = ZRenderType
