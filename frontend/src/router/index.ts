import { createRouter, createWebHistory } from 'vue-router'
import { installGuards } from './guard'
import { routes } from './routes'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

installGuards(router)

export default router
