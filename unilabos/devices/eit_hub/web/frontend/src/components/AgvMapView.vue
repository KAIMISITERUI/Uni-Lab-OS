<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgvMapStation } from '../api/agv'

const props = withDefaults(
  defineProps<{
    stations: AgvMapStation[]
    currentStationId?: string | null
    disabled?: boolean
    editable?: boolean
  }>(),
  {
    currentStationId: null,
    disabled: false,
    editable: false,
  },
)

const emit = defineEmits<{
  select: [stationId: string]
  'update:stations': [stations: AgvMapStation[]]
}>()

const mapElement = ref<HTMLElement | null>(null)
const draggingStationId = ref<string | null>(null)
const draggingPointerId = ref<number | null>(null)

const stationList = computed(() => props.stations ?? [])

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function updateStationPosition(stationId: string, event: PointerEvent) {
  const element = mapElement.value
  if (element === null) {
    return
  }
  const rect = element.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) {
    return
  }

  const x = clampPercent(((event.clientX - rect.left) / rect.width) * 100)
  const y = clampPercent(((event.clientY - rect.top) / rect.height) * 100)
  emit(
    'update:stations',
    stationList.value.map((station) => {
      if (station.id === stationId) {
        return { ...station, x, y }
      }
      return station
    }),
  )
}

function handleClick(stationId: string) {
  if (props.disabled === true || props.editable === true) {
    return
  }
  emit('select', stationId)
}

function handleStationPointerDown(stationId: string, event: PointerEvent) {
  if (props.editable === false) {
    return
  }
  event.preventDefault()
  draggingStationId.value = stationId
  draggingPointerId.value = event.pointerId
  const target = event.currentTarget as HTMLElement | null
  if (target !== null) {
    try {
      target.setPointerCapture(event.pointerId)
    } catch {
      // 浏览器未完成捕获时不影响拖拽坐标更新.
    }
  }
  updateStationPosition(stationId, event)
}

function handlePointerMove(event: PointerEvent) {
  if (props.editable === false || draggingStationId.value === null) {
    return
  }
  if (draggingPointerId.value !== null && draggingPointerId.value !== event.pointerId) {
    return
  }
  updateStationPosition(draggingStationId.value, event)
}

function stopDrag() {
  draggingStationId.value = null
  draggingPointerId.value = null
}
</script>

<template>
  <div
    ref="mapElement"
    class="agv-map"
    :class="{ 'agv-map-editable': props.editable === true }"
    @pointermove="handlePointerMove"
    @pointerup="stopDrag"
    @pointercancel="stopDrag"
  >
    <div class="map-grid-bg"></div>
    <template v-for="station in stationList" :key="station.id">
      <button
        class="map-station"
        :class="{
          'map-station-active': props.currentStationId === station.id,
          'map-station-editing': props.editable === true,
          'map-station-dragging': draggingStationId === station.id,
        }"
        :style="{ left: `${station.x}%`, top: `${station.y}%` }"
        :disabled="props.disabled === true && props.editable === false"
        :title="`${station.label} (${station.id}) - ${station.description}`"
        @pointerdown="handleStationPointerDown(station.id, $event)"
        @click="handleClick(station.id)"
      >
        <span class="station-id">{{ station.id }}</span>
        <span class="station-label">{{ station.label }}</span>
      </button>
    </template>
    <div v-if="stationList.length === 0" class="muted map-empty">
      正在加载工站布局...
    </div>
  </div>
</template>

<style scoped>
.agv-map {
  position: relative;
  width: 100%;
  min-height: 320px;
  background: #f7f9fc;
  border: 1px dashed #cbd5e5;
  border-radius: 8px;
  overflow: hidden;
}

.agv-map-editable {
  border-color: #1a75cf;
  border-style: solid;
}

.map-grid-bg {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, rgba(26, 117, 207, 0.08) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(26, 117, 207, 0.08) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}

.map-station {
  position: absolute;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 88px;
  padding: 8px 10px;
  color: #12325a;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(18, 50, 90, 0.1);
  transition: transform 0.1s ease;
  touch-action: none;
}

.map-station:hover:not(:disabled) {
  transform: translate(-50%, -50%) scale(1.05);
  border-color: #1a75cf;
}

.map-station:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.map-station-editing {
  cursor: grab;
  opacity: 1;
}

.map-station-dragging {
  cursor: grabbing;
  transform: translate(-50%, -50%) scale(1.08);
  border-color: #1a75cf;
  box-shadow: 0 10px 24px rgba(26, 95, 168, 0.24);
}

.map-station-active {
  color: #ffffff;
  background: #1a5fa8;
  border-color: #1a5fa8;
  box-shadow: 0 8px 20px rgba(26, 95, 168, 0.3);
}

.station-id {
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 1px;
}

.station-label {
  font-size: 13px;
}

.map-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
