export interface VesselSvgItem {
  v_front: any;
  v_right: any;
  v_back?: any;
  v_left?: any;
  v_front_2d?: any;
  v_right_2d?: any;
  v_left_2d?: any;
  v_back_2d?: any;
  [propName: string]: any;
}
export interface VesselSvgType extends Record<string, VesselSvgItem> {}

export const NTU: VesselSvgType = {
}

export const VesselSvgMap: VesselSvgType = {
  ...NTU
}
