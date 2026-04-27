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
}

export type _ZRenderType = ZRenderType
