import { onBeforeUnmount, ref, type Ref } from 'vue'

/**
 * 功能:
 *   全局唯一的 "桌面端/手机端" 响应式状态.
 *   断点 768px (与 Element Plus sm 对齐, 覆盖主流手机机型).
 *   组件挂载时自动监听 matchMedia 变化, 卸载时清理监听器.
 * 参数:
 *   无.
 * 返回:
 *   { isMobile, isDesktop } 两个 Ref<boolean>, 互为反向同步状态.
 */
const MOBILE_QUERY = '(max-width: 767.98px)'

interface ViewportMode {
  isMobile: Ref<boolean>
  isDesktop: Ref<boolean>
}

export function useViewportMode (): ViewportMode {
  // SSR 安全 兜底: 无 window 时退化为 desktop 默认
  const hasWindow = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const isMobile = ref<boolean>(false)
  const isDesktop = ref<boolean>(true)

  if (hasWindow === false) {
    return { isMobile, isDesktop }
  }

  const mediaQueryList = window.matchMedia(MOBILE_QUERY)

  // 同步当前状态
  isMobile.value = mediaQueryList.matches === true
  isDesktop.value = mediaQueryList.matches === false

  function handleChange (event: MediaQueryListEvent): void {
    // 媒体查询命中变化时, 立即同步两个状态
    isMobile.value = event.matches === true
    isDesktop.value = event.matches === false
  }

  // 兼容旧 API (Safari 13 以前用 addListener); 现代浏览器优先 addEventListener
  if (typeof mediaQueryList.addEventListener === 'function') {
    mediaQueryList.addEventListener('change', handleChange)
  } else {
    // 旧浏览器回退路径
    mediaQueryList.addListener(handleChange)
  }

  onBeforeUnmount(() => {
    if (typeof mediaQueryList.removeEventListener === 'function') {
      mediaQueryList.removeEventListener('change', handleChange)
    } else {
      mediaQueryList.removeListener(handleChange)
    }
  })

  return { isMobile, isDesktop }
}
