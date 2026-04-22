import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/synthesis',
  },
  {
    path: '/synthesis',
    name: 'synthesis',
    component: () => import('../views/SynthesisView.vue'),
    meta: { title: '合成工站' },
  },
  {
    path: '/chemicals',
    name: 'chemicals',
    component: () => import('../views/ChemicalsView.vue'),
    meta: { title: '化学品库' },
  },
  {
    path: '/chemical-integrity',
    name: 'chemical-integrity',
    component: () => import('../views/IntegrityView.vue'),
    meta: { title: '完整性维护' },
  },
  {
    path: '/analysis',
    name: 'analysis',
    component: () => import('../views/PlaceholderView.vue'),
    meta: { title: '分析工站' },
  },
  {
    path: '/agv',
    name: 'agv',
    component: () => import('../views/PlaceholderView.vue'),
    meta: { title: 'AGV 工站' },
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
