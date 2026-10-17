import { computed, createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElInfiniteScroll,
  ElLoading,
  ElMessage,
  ElMessageBox,
  ElNotification,
  ElPopoverDirective,
  provideGlobalConfig,
} from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import './composables/useTheme'
import App from './App.vue'
import router from './router'
import { initAuth } from './auth/client'
import { elementLocale, i18n, t } from './i18n'
import { vPermission } from './directives/permission'
import './styles/global.css'
import './styles/theme.css'

async function bootstrap(): Promise<void> {
  // Redirects to Keycloak (Authorization Code + PKCE) when there is no session.
  await initAuth()

  const app = createApp(App)
  app.use(createPinia())
  app.use(i18n)
  app.use(router)
  // Components are imported on demand (vite.config.ts); these are the plugin-style APIs.
  for (const plugin of [
    ElInfiniteScroll,
    ElLoading,
    ElMessage,
    ElMessageBox,
    ElNotification,
    ElPopoverDirective,
  ]) {
    app.use(plugin)
  }
  provideGlobalConfig(
    computed(() => ({ locale: elementLocale.value })),
    app,
    true,
  )
  app.directive('permission', vPermission)
  app.mount('#app')
}

bootstrap().catch((err: unknown) => {
  console.error(err)
  document.getElementById('app')!.innerHTML =
    `<p style="padding:24px">${t('layout.authUnavailable')}</p>`
})
