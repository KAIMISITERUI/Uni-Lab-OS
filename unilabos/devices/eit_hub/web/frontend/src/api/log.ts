// 前端结果区使用的结构化日志条目, 与后端 web/log_entry.py 保持一致.
// ts: ISO 8601 秒级时间戳, 由后端打入.
// level: 仅有 info / success / warning / error 四种, 直接驱动样式与图标.
// source: 来源标识, 一般是工作流步骤 ID 或子模块名, 留空则不显示.
// message: 日志正文.

export type LogLevel = 'info' | 'success' | 'warning' | 'error'

export interface LogEntry {
  ts: string
  level: LogLevel
  source: string
  message: string
}
