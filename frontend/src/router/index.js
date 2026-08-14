import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/knowledge' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue'),
    },
    {
      path: '/',
      component: () => import('../layout/MainLayout.vue'),
      children: [
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('../views/Knowledge.vue'),
        },
        {
          path: 'permission',
          name: 'permission',
          component: () => import('../views/Permission.vue'),
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('../views/Dashboard.vue'),
        },
        {
          path: 'logs',
          name: 'logs',
          component: () => import('../views/Logs.vue'),
        },
        {
          path: 'operations',
          name: 'operations',
          component: () => import('../views/Operations.vue'),
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('../views/Users.vue'),
        },
        {
          path: 'tasks',
          name: 'tasks',
          component: () => import('../views/Tasks.vue'),
        },
        {
          path: 'task-stats',
          name: 'task-stats',
          component: () => import('../views/TaskStats.vue'),
        },
      ],
    },
  ],
})

// 登录守卫
router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.path !== '/login' && !token) {
    return '/login'
  }
  if (to.path === '/login' && token) {
    return '/knowledge'
  }
})

export default router
