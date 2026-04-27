import type { BaseTray } from './tray'
import type { Station } from '../station/station'

// 支持两种类型的任务：托盘和工位
export type SyncTask =
  | { type: 'tray', tray: BaseTray, startIdx: number }
  | { type: 'station', station: Station, startIdx: number }

class SyncManager {
  private static trayTasks: Map<BaseTray, { tray: BaseTray, startIdx: number }> = new Map()
  private static stationTasks: Map<Station, { station: Station, startIdx: number }> = new Map()
  private static isRunning: boolean = false
  private static batchSize: number = 2000

  static addTrayTask (tray: BaseTray, startIdx: number = 0): void {
    this.trayTasks.set(tray, { tray, startIdx })
    this.start()
  }

  static addStationTask (station: Station, startIdx: number = 0): void {
    this.stationTasks.set(station, { station, startIdx })
    this.start()
  }

  private static start (): void {
    if (!this.isRunning) {
      this.isRunning = true
      requestAnimationFrame(this.run.bind(this))
    }
  }

  private static run (): void {
    let count = 0
    // 优先处理 tray
    for (const [tray, task] of this.trayTasks) {
      let idx = task.startIdx
      const total = tray.children.length
      const end = Math.min(idx + 2000, total)
      for (; idx < end; idx++) {
        tray.syncItem(idx)
        count++
      }
      if (idx < total) {
        task.startIdx = idx
        // 保留未完成的任务
      } else {
        this.trayTasks.delete(tray)
      }
      if (count >= this.batchSize) break
    }
    // station 同理
    for (const [station, task] of this.stationTasks) {
      let idx = task.startIdx
      const slotKeys = Object.keys(station.slots)
      const total = slotKeys.length
      const end = Math.min(idx + 50, total)
      for (; idx < end; idx++) {
        const slot = station.slots[slotKeys[idx]]
        slot && slot.updateView && slot.updateView()
        count++
      }
      if (idx < total) {
        task.startIdx = idx
      } else {
        this.stationTasks.delete(station)
      }
      if (count >= this.batchSize) break
    }
    if (this.trayTasks.size || this.stationTasks.size) {
      requestAnimationFrame(this.run.bind(this))
    } else {
      this.isRunning = false
    }
  }
}

export default SyncManager
