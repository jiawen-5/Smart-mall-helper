import { createRouter, createWebHistory } from 'vue-router'
import DataDashboard from '../views/DataDashboard.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: DataDashboard,
    },
    {
      path: '/products',
      name: 'products',
      component: () => import('../views/ProductIntelligence.vue'),
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/AiOperationAssistant.vue'),
    },
    {
      path: '/assistant/chat',
      name: 'assistant-chat',
      component: () => import('../views/AiChatPage.vue'),
    },
    {
      path: '/insights',
      name: 'insights',
      component: () => import('../views/UserInsights.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

export default router
