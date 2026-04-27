<template>
  <div ref="scrollRef" class="result-console" :style="rootStyle">
    <div v-if="entries.length === 0" class="muted">{{ emptyText ?? '暂无运行结果' }}</div>
    <div
      v-for="(entry, index) in entries"
      :key="`${index}-${entry.ts}`"
      :class="['result-line', `level-${entry.level}`]"
    >
      <span class="ts">{{ formatTs(entry.ts) }}</span>
      <el-icon class="icon"><component :is="iconFor(entry.level)" /></el-icon>
      <span v-if="entry.source" class="src">{{ entry.source }}</span>
      <span class="msg">{{ entry.message }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  CircleCheckFilled,
  CircleCloseFilled,
  InfoFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import type { LogEntry, LogLevel } from '../api/log'

interface Props {
  entries: LogEntry[]
  emptyText?: string
  maxHeight?: string
}

const props = withDefaults(defineProps<Props>(), {
  emptyText: '暂无运行结果',
  maxHeight: '260px',
})

const scrollRef = ref<HTMLDivElement | null>(null)

const rootStyle = computed(() => ({ maxHeight: props.maxHeight }))

// 仅在条目数变化时滚动到底, 避免重复 reactive 触发抖动
watch(
  () => props.entries.length,
  () => {
    void nextTick(() => {
      const node = scrollRef.value
      if (node !== null) {
        node.scrollTop = node.scrollHeight
      }
    })
  },
)

const ICONS: Record<LogLevel, unknown> = {
  info: InfoFilled,
  success: CircleCheckFilled,
  warning: WarningFilled,
  error: CircleCloseFilled,
}

function iconFor(level: LogLevel): unknown {
  return ICONS[level] ?? InfoFilled
}

function formatTs(ts: string): string {
  // 后端输出 ISO 8601 (秒级), 取时分秒展示, 异常输入降级为原值
  const tIndex = ts.indexOf('T')
  if (tIndex === -1) {
    return ts
  }
  const tail = ts.slice(tIndex + 1)
  return tail.length >= 8 ? tail.slice(0, 8) : tail
}
</script>

<style scoped>
.result-console {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: auto;
  padding: 10px 12px;
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 12px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  color: #24344d;
}

.muted {
  color: #94a3b8;
  font-size: 12px;
}

.result-line {
  display: grid;
  grid-template-columns: auto auto auto 1fr;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 8px;
  border-left: 3px solid #94a3b8;
  background: transparent;
  border-radius: 2px;
  line-height: 1.5;
  word-break: break-all;
}

.result-line .ts {
  color: #94a3b8;
  font-size: 11px;
  white-space: nowrap;
}

.result-line .icon {
  font-size: 14px;
  color: #94a3b8;
}

.result-line .src {
  color: #6b7c93;
  background: #eef2f7;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 11px;
  white-space: nowrap;
}

.result-line .msg {
  color: #24344d;
  white-space: pre-wrap;
}

/* info 级别采用中性色, 仅作为基线视觉 */
.result-line.level-info {
  border-left-color: #7a8aa3;
}
.result-line.level-info .icon {
  color: #7a8aa3;
}

/* success 级别使用绿色, 用于步骤完成 / 任务成功等正向终态事件 */
.result-line.level-success {
  border-left-color: #67c23a;
}
.result-line.level-success .icon {
  color: #67c23a;
}
.result-line.level-success .msg {
  color: #2f6f1f;
}

/* warning 级别使用橙色, 用于暂停 / 停止请求 / 软失败重试等中间态 */
.result-line.level-warning {
  border-left-color: #e6a23c;
}
.result-line.level-warning .icon {
  color: #e6a23c;
}
.result-line.level-warning .msg {
  color: #8a5a08;
}

/* error 级别使用红色, 用于步骤失败 / 任务失败等终止性事件 */
.result-line.level-error {
  border-left-color: #f56c6c;
}
.result-line.level-error .icon {
  color: #f56c6c;
}
.result-line.level-error .msg {
  color: #a32d2d;
}
</style>
