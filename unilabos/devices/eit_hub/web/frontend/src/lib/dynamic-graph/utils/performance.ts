/**
 * 性能优化工具类
 * 提供统一的性能监控和优化方法
 */

export class PerformanceOptimizer {
  private static instance: PerformanceOptimizer
  private performanceMetrics: Map<string, number[]> = new Map()
  private isMonitoring: boolean = false

  static getInstance (): PerformanceOptimizer {
    if (!PerformanceOptimizer.instance) {
      PerformanceOptimizer.instance = new PerformanceOptimizer()
    }
    return PerformanceOptimizer.instance
  }

  // 开始性能监控
  startMonitoring (): void {
    this.isMonitoring = true
    console.log('Performance monitoring started')
  }

  // 停止性能监控
  stopMonitoring (): void {
    this.isMonitoring = false
    console.log('Performance monitoring stopped')
  }

  // 记录性能指标
  recordMetric (name: string, duration: number): void {
    if (!this.isMonitoring) return

    if (!this.performanceMetrics.has(name)) {
      this.performanceMetrics.set(name, [])
    }
    this.performanceMetrics.get(name)!.push(duration)

    // 如果执行时间过长，输出警告
    if (duration > 100) {
      console.warn(`Performance warning: ${name} took ${duration.toFixed(2)}ms`)
    }
  }

  // 获取性能报告
  getPerformanceReport (): Record<string, {
    count: number;
    avg: number;
    min: number;
    max: number;
    total: number;
  }> {
    const report: Record<string, any> = {}

    this.performanceMetrics.forEach((durations: number[], name: string) => {
      const count = durations.length
      const total = durations.reduce((sum: number, d: number) => sum + d, 0)
      const avg = total / count
      const min = Math.min(...durations)
      const max = Math.max(...durations)

      report[name] = { count, avg, min, max, total }
    })

    return report
  }

  // 清理性能数据
  clearMetrics (): void {
    this.performanceMetrics.clear()
  }

  // 性能装饰器
  static measure (target: any, propertyName: string, descriptor: PropertyDescriptor): PropertyDescriptor {
    const method = descriptor.value

    descriptor.value = function (...args: any[]): any {
      const start = performance.now()
      const result = method.apply(this, args)
      const end = performance.now()

      PerformanceOptimizer.getInstance().recordMetric(`${target.constructor.name}.${propertyName}`, end - start)

      return result
    }

    return descriptor
  }

  // 批量操作优化
  static batchOperation<T> (
    items: T[],
    operation: (item: T) => void,
    batchSize: number = 20,
    delay: number = 16
  ): Promise<void> {
    return new Promise((resolve: () => void) => {
      let currentIndex = 0

      const processBatch = (): void => {
        const endIndex = Math.min(currentIndex + batchSize, items.length)

        for (let i = currentIndex; i < endIndex; i++) {
          operation(items[i])
        }

        currentIndex = endIndex

        if (currentIndex < items.length) {
          setTimeout(processBatch, delay)
        } else {
          resolve()
        }
      }

      processBatch()
    })
  }

  // 防抖函数
  static debounce<T extends (...args: any[]) => any>(
    func: T,
    wait: number): (...args: Parameters<T>) => void {
    let timeout: NodeJS.Timeout | null = null

    return (...args: Parameters<T>): void => {
      if (timeout) {
        clearTimeout(timeout)
      }
      timeout = setTimeout(() => func(...args), wait)
    }
  }

  // 节流函数
  static throttle<T extends (...args: any[]) => any>(
    func: T,
    limit: number): (...args: Parameters<T>) => void {
    let inThrottle: boolean = false

    return (...args: Parameters<T>): void => {
      if (!inThrottle) {
        func(...args)
        inThrottle = true
        setTimeout(() => { inThrottle = false }, limit)
      }
    }
  }

  // 内存使用监控
  static getMemoryUsage (): { used: number; total: number; limit: number } | null {
    if ((performance as any).memory) {
      const { memory } = performance as any
      return {
        used: memory.usedJSHeapSize,
        total: memory.totalJSHeapSize,
        limit: memory.jsHeapSizeLimit
      }
    }
    return null
  }

  // 检查是否需要清理缓存
  static shouldClearCache (thresholdMB: number = 100): boolean {
    const memoryUsage = this.getMemoryUsage()
    if (memoryUsage) {
      return memoryUsage.used > thresholdMB * 1024 * 1024
    }
    return false
  }
}

// 导出单例实例
export const performanceOptimizer = PerformanceOptimizer.getInstance()
