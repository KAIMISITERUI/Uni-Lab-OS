<script setup lang="ts">
import { computed } from 'vue'
import type { ShelfSlotInfo } from '../api/agv'

const props = defineProps<{
  slots: Record<string, ShelfSlotInfo | null>
}>()

const emit = defineEmits<{
  slotClick: [slotName: string, info: ShelfSlotInfo | null]
}>()

const ROWS = [1, 2, 3]
const COLS = [1, 2, 3, 4]

const slotMatrix = computed(() => {
  return ROWS.map((row) =>
    COLS.map((col) => {
      const name = `shelf_tray_${row}-${col}`
      return {
        name,
        info: props.slots?.[name] ?? null,
      }
    }),
  )
})

function handleClick(slotName: string, info: ShelfSlotInfo | null) {
  emit('slotClick', slotName, info)
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return '--'
  }
  return value.replace('T', ' ').substring(0, 19)
}
</script>

<template>
  <div class="shelf-wrap">
    <div v-for="(row, rowIdx) in slotMatrix" :key="rowIdx" class="shelf-row">
      <div class="shelf-row-label">第 {{ rowIdx + 1 }} 层</div>
      <div class="shelf-row-slots">
        <button
          v-for="cell in row"
          :key="cell.name"
          class="shelf-slot"
          :class="{ 'slot-empty': cell.info === null, 'slot-occupied': cell.info !== null }"
          @click="handleClick(cell.name, cell.info)"
        >
          <div class="slot-title">{{ cell.name }}</div>
          <template v-if="cell.info !== null">
            <div class="slot-material">{{ cell.info.material_type }}</div>
            <div class="slot-source">来源: {{ cell.info.source || '--' }}</div>
            <div class="slot-time">{{ formatTimestamp(cell.info.placed_at) }}</div>
          </template>
          <template v-else>
            <div class="slot-empty-label">空闲</div>
          </template>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shelf-wrap {
  display: grid;
  gap: 12px;
}

.shelf-row {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.shelf-row-label {
  color: #34445d;
  font-weight: 600;
  font-size: 13px;
}

.shelf-row-slots {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.shelf-slot {
  display: grid;
  gap: 4px;
  min-height: 92px;
  padding: 12px;
  color: #24344d;
  text-align: left;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  cursor: pointer;
  transition: box-shadow 0.1s ease, border-color 0.1s ease;
}

.shelf-slot:hover {
  box-shadow: 0 4px 12px rgba(18, 50, 90, 0.1);
  border-color: #1a75cf;
}

.slot-empty {
  background: #f7f9fc;
  color: #738196;
}

.slot-occupied {
  background: #eef6ff;
  border-color: #b5d2f0;
}

.slot-title {
  font-weight: 600;
  font-size: 12px;
  color: #12325a;
}

.slot-material {
  font-weight: 600;
  font-size: 13px;
}

.slot-source,
.slot-time {
  color: #66758a;
  font-size: 11px;
}

.slot-empty-label {
  margin-top: 8px;
  font-size: 13px;
  color: #a1a9b8;
}

@media (max-width: 768px) {
  .shelf-row-slots {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
