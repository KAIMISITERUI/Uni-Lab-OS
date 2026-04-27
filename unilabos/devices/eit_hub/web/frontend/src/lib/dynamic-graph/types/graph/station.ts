import type { Recorder } from 'Types/graph/graph'

export interface StationData {
  raw: any; // svg原始内容
  cached?: boolean;
  dom?: any; // svg转换为dom对象
  recorder?: Recorder; // 尺子和锚点的缓存
  mul?: Record<string, StationData>
  [propName: string]: any;
}
