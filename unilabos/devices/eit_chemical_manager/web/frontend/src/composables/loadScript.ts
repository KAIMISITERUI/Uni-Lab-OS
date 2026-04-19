/**
 * 功能:
 *     动态向 document.head 注入 <script> 标签并在加载完成时 resolve
 * 说明:
 *     - Emscripten UMD 产物依赖全局作用域的 var 声明, 必须用普通 <script>
 *       加载 (而非 <script type="module">), 否则顶层 var 不会挂到 window 上
 *     - 同一个 src 重复调用直接复用已有 script, 防止重复加载与回调
 *     - 加载失败抛出 Error, 由调用方决定如何反馈
 * 参数:
 *     src 脚本的绝对路径 (相对于站点根, 例如 /rdkit/RDKit_minimal.js)
 * 返回:
 *     Promise<void>, script 触发 load 事件后 resolve
 */
const inflight = new Map<string, Promise<void>>()

export function loadScript(src: string): Promise<void> {
  const existing = inflight.get(src)
  if (existing !== undefined) {
    return existing
  }
  const promise = new Promise<void>((resolve, reject) => {
    const element = document.createElement('script')
    element.src = src
    element.async = true
    element.addEventListener('load', () => resolve())
    element.addEventListener('error', () => {
      // 加载失败时允许后续重试, 移除缓存项
      inflight.delete(src)
      reject(new Error(`脚本加载失败: ${src}`))
    })
    document.head.appendChild(element)
  })
  inflight.set(src, promise)
  return promise
}
