declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

// Element Plus 中文语言包没有自带类型声明
declare module 'element-plus/dist/locale/zh-cn.mjs'
