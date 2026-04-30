import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/devices',
  },
  {
    path: '/devices',
    name: 'devices',
    component: () => import('../views/DeviceStatusView.vue'),
    meta: { title: '设备总览' },
  },
  {
    path: '/synthesis',
    name: 'synthesis',
    component: () => import('../views/SynthesisView.vue'),
    meta: { title: '合成工站' },
  },
  {
    path: '/synthesis/cameras',
    name: 'synthesis-cameras',
    component: () => import('../views/SynthesisCameraView.vue'),
    meta: { title: '现场监控' },
  },
  {
    path: '/analysis',
    name: 'analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '分析工站' },
  },
  {
    path: '/agv',
    name: 'agv',
    component: () => import('../views/AgvStatusView.vue'),
    meta: { title: 'AGV 运输车' },
  },
  {
    path: '/agv/positions',
    name: 'agv-positions',
    component: () => import('../views/AgvCalibrationView.vue'),
    meta: { title: 'AGV 点位管理' },
  },
  {
    path: '/agv/shelf',
    name: 'agv-shelf',
    component: () => import('../views/AgvShelfView.vue'),
    meta: { title: 'AGV 货架' },
  },
  {
    path: '/chemicals',
    name: 'chemicals',
    component: () => import('../views/ChemicalsView.vue'),
    meta: { title: '化学品库' },
  },
  {
    path: '/synthesis-task-editor',
    name: 'synthesis-task-editor',
    component: () => import('../views/SynthesisTaskEditorView.vue'),
    meta: { title: '任务编辑' },
  },
  {
    path: '/synthesis-workflow',
    name: 'synthesis-workflow',
    component: () => import('../views/SynthesisWorkflowView.vue'),
    meta: { title: '工作流' },
  },
  {
    path: '/task-history',
    name: 'task-history',
    component: () => import('../views/TaskHistoryView.vue'),
    meta: { title: '任务历史' },
  },
  {
    path: '/maintenance',
    name: 'maintenance',
    component: () => import('../views/MaintenanceView.vue'),
    meta: { title: '运维管理' },
  },
  {
    path: '/label-printer',
    name: 'label-printer',
    component: () => import('../views/LabelPrinterView.vue'),
    meta: { title: '标签打印机' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
