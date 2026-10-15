import { createApp } from 'vue'
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
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import './composables/useTheme'
import App from './App.vue'
import router from './router'
import { initAuth } from './auth/client'
import { vPermission } from './directives/permission'
import './styles/global.css'
import './styles/theme.css'

async function bootstrap(): Promise<void> {
  // Redirects to Keycloak (Authorization Code + PKCE) when there is no session.
  await initAuth()

  const app = createApp(App)
  app.use(createPinia())
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
  provideGlobalConfig({ locale: zhCn }, app, true)
  app.directive('permission', vPermission)
  app.mount('#app')
}

bootstrap().catch((err: unknown) => {
  console.error(err)
  document.getElementById('app')!.innerHTML =
    '<p style="padding:24px">无法连接认证服务，请稍后刷新重试。</p>'
})
