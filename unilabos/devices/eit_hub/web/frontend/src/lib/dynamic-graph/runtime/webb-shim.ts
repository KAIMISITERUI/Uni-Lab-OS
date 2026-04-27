/**
 * 功能:
 *   在 Vue 应用启动前注入 dynamic-graph 期望的全局: window.webb (含 store.get('params')) 与 window.i18n.
 *   原工程依赖 webb 微前端壳运行期下发 params, 我们没有壳, 因此用静态 JSON 直接铺设.
 * 用法:
 *   在 main.ts 顶部 createApp 之前调用 setupWebbShim()
 */
import * as Vue from 'vue'
import ntuModel from './ntu-model.json'
import ntuPatch from './ntu-patch.json'

declare global {
  interface Window {
    webb?: any
    Vue?: any
    i18n?: any
  }
}

export function setupWebbShim (): void {
  // 静态 params, 与 dynamic-service config/dynamic.config.example.json 中的运行期注入对齐.
  // $view 决定当前工作站 (NTU 即宁波理工合成工作站)
  const params = {
    $view: 'NTU',
    model: ntuModel,
    patch: ntuPatch,
    hostname: '/synthesis-api',
    pollingInterval: 10,
    noBuffer3: true
  }

  if (!window.webb) {
    window.webb = {
      store: {
        get: (key: string) => (key === 'params' ? params : {})
      },
      utils: {}
    }
  }

  // dynamic-graph tray.ts 顶部读 window.Vue, 部分组件需要全局 Vue 引用
  if (!window.Vue) {
    window.Vue = Vue
  }

  // station.ts 读取 window.i18n.locale.value 决定 SVG 语言变体, 默认中文
  if (!window.i18n) {
    window.i18n = {
      locale: { value: 'zh' }
    }
  }
}
