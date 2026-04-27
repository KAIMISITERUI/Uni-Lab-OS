export declare enum SubstanceUnit {
    ml = 'ml',
    mg = 'mg'
}
export interface TrayLayout {
    start?: string;
    direction?: string;
    grouped?: boolean;
    groupedOriginChar?: string;
    charPosition?: string // 字符的位置
    [propName: string]: any;
}
export interface TrayTask {
    compName?: string;
    roles?: Array<string>;
    [propName: string]: any;
}
export interface ActionControl {
    create?: boolean;
    update?: boolean;
    [propName: string]: any;
}
/**
 * 托盘型号的默认配置参数
 * 可在资源视图组件中定义托盘型号的定制化参数，覆盖默认参数
 */
export interface TrayConfig {
  model: string; // 型号 TT8T
  children_count: number; // 子节点数量
  tray_front: any; // 托盘的svg
  tray_right: any;
  tray_back?: any;
  tray_left?: any;
  name?: string; // 型号名称
  row?: number; // (视图层)行数
  col?: number; // (视图层)列数
  isFull?: boolean; // 是否为整版，进料时不可单独进介质(默认满配); 默认值为false
  isSiamese?: boolean // 是否为一体，托盘上放一个 child，只有一个二维码
  isEmpty?: boolean; // 是否为空托盘，即进料时只能空托盘进料(默认全部孔位为空); 默认值为false, 与isFull互斥
  likeFull?: boolean // 空托盘类型可配置，配置完录入资源可支持编辑数量
  isCapTray?: boolean // 是否为盖子类型的托盘
  capType?: number // 托盘盖子的类型 1 为普通盖子， 2为穿刺盖子
  modelBranchMaster?: string, // 表示托盘分支的头
  updateChildCount?: ActionControl; // 更新(增删)子节点数量的控制；（如果资源视图的编辑组件使用的是高级模式则具有编辑介质数量功能，普通模式无此功能）
  editTrayBarcode?: ActionControl; // 编辑托盘条码的控制; 默认(无配置时)可编辑(非整版)托盘条码
  editCaps?: ActionControl;
  editVesselBarcode?: ActionControl; // 编辑介质条码的控制; 默认(无配置时)可编辑(非整版)介质条码
  editSubstance?: ActionControl; // 编辑物质的控制
  substanceUnit?: SubstanceUnit[]; // 录入物质时的默认单位
  slotInMultipleRows?: boolean; // 槽位为多行布局，影响任务单元视图中槽位展示，默认为false
  layout?: TrayLayout; // (视图层)布局相关
  task?: TrayTask; // 托盘型号作用于任务的相关配置
  with_cap?: Record<string, boolean>;
  range?: Array<string>; // 适用的业务场景，值为webb continer
  [propName: string]: any;
}

export interface VesselConfig {
  model: string;
  range?: Array<string>
  capType?: number // 托盘盖子的类型 1 为普通盖子， 2为穿刺盖子
  [propName: string]: any;
}

export interface SlotLabelInfo {
  rowIndexLabel: string,
  colIndexLabel: string,
  slot_index: number;
  slot_label: string;
}
