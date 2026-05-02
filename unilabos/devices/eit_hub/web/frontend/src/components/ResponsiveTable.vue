<script setup lang="ts" generic="T extends Record<string, unknown>">
/**
 * 功能:
 *   响应式表格容器. 桌面端透传 default slot (内部继续使用 el-table 不变);
 *   手机端 (max-width: 767.98px) 切换为卡片列表渲染, 每行一张卡片,
 *   primary 字段作为卡片大标题, 其余字段以 标签:值 行排版,
 *   操作按钮 (cardActions) 渲染在卡片底部按钮组.
 *
 *   slot 命名约定:
 *     cell:{key}  自定义字段值渲染, 与桌面端 el-table-column #default="{ row }" 保持对齐
 *
 * 参数:
 *   data:        T[]            行数据数组, 与 el-table :data 同源
 *   rowKey:      string         行唯一键的字段名
 *   cardFields:  CardField[]    卡片模式展示的字段列表; 第一个 primary: true 视为大标题
 *   cardActions: (row) => Array 卡片底部按钮列表 (可选)
 *
 * 返回:
 *   无 (Vue 组件)
 */
import { computed } from 'vue'
import { useViewportMode } from '../composables/useViewportMode'

interface CardField<R> {
  key: string
  label: string
  // 可选格式化函数; 不提供时直接读取 row[key]
  render?: (row: R) => unknown
  // 是否作为卡片大标题 (有且只有一个为 true 的字段会被提为标题)
  primary?: boolean
}

interface CardAction {
  label: string
  // 复用 el-button type 取值, primary/success/warning/danger/info/text 任选
  type?: '' | 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'text'
  link?: boolean
  onClick: () => void
}

interface Props {
  data: T[]
  // rowKey 与 el-table 同语义: 可传字段名 (如 'id'), 也可传函数 (如 (row) => `${row.a}|${row.b}`)
  rowKey: string | ((row: T) => string)
  cardFields: CardField<T>[]
  cardActions?: (row: T) => CardAction[]
}

const props = defineProps<Props>()

const { isMobile } = useViewportMode()

// 默认情况下, 第一个标记 primary 的字段作为大标题; 若无标记则使用 cardFields[0]
const primaryFieldDef = computed<CardField<T> | null>(() => {
  if (props.cardFields.length === 0) {
    return null
  }
  const explicit = props.cardFields.find((field) => field.primary === true)
  if (explicit !== undefined) {
    return explicit
  }
  return props.cardFields[0]
})

const secondaryFieldDefs = computed<CardField<T>[]>(() => {
  if (primaryFieldDef.value === null) {
    return []
  }
  const primaryKey = primaryFieldDef.value.key
  return props.cardFields.filter((field) => field.key !== primaryKey)
})

function resolveValue (row: T, field: CardField<T>): unknown {
  if (typeof field.render === 'function') {
    return field.render(row)
  }
  return row[field.key]
}

function rowKeyOf (row: T): string {
  // 行唯一标识, 用于 v-for key
  if (typeof props.rowKey === 'function') {
    return props.rowKey(row)
  }
  const value = (row as Record<string, unknown>)[props.rowKey]
  return String(value)
}
</script>

<template>
  <div v-if="isMobile" class="responsive-card-list">
    <div
      v-for="row in props.data"
      :key="rowKeyOf(row)"
      class="responsive-card"
    >
      <div v-if="primaryFieldDef !== null" class="responsive-card-title">
        <span class="responsive-card-title-value" :data-card-field="primaryFieldDef.key">
          <slot
            :name="`cell:${primaryFieldDef.key}`"
            :row="row"
            :field="primaryFieldDef"
          >
            {{ resolveValue(row, primaryFieldDef) }}
          </slot>
        </span>
      </div>
      <div class="responsive-card-body">
        <div
          v-for="field in secondaryFieldDefs"
          :key="field.key"
          class="responsive-card-row"
          :data-card-field="field.key"
        >
          <span class="responsive-card-label" :data-card-field="field.key">{{ field.label }}</span>
          <span class="responsive-card-value" :data-card-field="field.key">
            <slot
              :name="`cell:${field.key}`"
              :row="row"
              :field="field"
            >
              {{ resolveValue(row, field) }}
            </slot>
          </span>
        </div>
      </div>
      <div
        v-if="props.cardActions !== undefined"
        class="responsive-card-actions"
      >
        <el-button
          v-for="action in props.cardActions(row)"
          :key="action.label"
          :type="action.type"
          :link="false"
          :plain="action.link === true"
          size="small"
          @click="action.onClick"
        >
          {{ action.label }}
        </el-button>
      </div>
    </div>
    <div v-if="props.data.length === 0" class="responsive-card-empty">
      暂无数据
    </div>
  </div>
  <slot v-else />
</template>
