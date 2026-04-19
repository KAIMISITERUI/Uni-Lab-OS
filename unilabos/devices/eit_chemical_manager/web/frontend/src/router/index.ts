import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chemicals',
  },
  {
    path: '/chemicals',
    name: 'chemicals',
    component: () => import('../views/ChemicalsView.vue'),
    meta: { title: '化学品列表' },
  },
  {
    path: '/integrity',
    name: 'integrity',
    component: () => import('../views/IntegrityView.vue'),
    meta: { title: '完整性维护' },
  },
  {
    // 开发期渲染器对比评估页, 选型确定后整体删除
    path: '/dev/renderer-compare',
    name: 'renderer-compare',
    component: () => import('../views/dev/RendererCompareView.vue'),
    meta: { title: '渲染器对比 (评估)' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
