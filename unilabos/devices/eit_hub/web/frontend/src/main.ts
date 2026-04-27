import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles.css'
import { setupWebbShim } from './lib/dynamic-graph/runtime/webb-shim'

// dynamic-graph 期望在 createApp 之前注入 window.webb / window.Vue / window.i18n
setupWebbShim()

const app = createApp(App)

app.use(router)
app.use(ElementPlus, { locale: zhCn })

for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.mount('#app')

