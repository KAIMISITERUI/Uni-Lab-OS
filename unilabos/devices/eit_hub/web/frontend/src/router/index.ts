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
    path: '/analysis',
    name: 'analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '分析工站' },
  },
  {
    path: '/agv',
    name: 'agv',
    component: () => import('../views/AgvStatusView.vue'),
    meta: { title: 'AGV 状态' },
  },
  {
    path: '/agv/calibration',
    name: 'agv-calibration',
    component: () => import('../views/AgvCalibrationView.vue'),
    meta: { title: 'AGV 点位校准' },
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
    path: '/label-printer',
    name: 'label-printer',
    component: () => import('../views/PlaceholderView.vue'),
    meta: { title: '标签打印机' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
