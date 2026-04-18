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
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
