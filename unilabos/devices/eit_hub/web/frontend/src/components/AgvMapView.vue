<script setup lang="ts">
import { computed } from 'vue'
import type { AgvMapStation } from '../api/agv'

const props = withDefaults(
  defineProps<{
    stations: AgvMapStation[]
    currentStationId?: string | null
    disabled?: boolean
  }>(),
  {
    currentStationId: null,
    disabled: false,
  },
)

const emit = defineEmits<{
  select: [stationId: string]
}>()

const stationList = computed(() => props.stations || [])

function handleClick(stationId: string) {
  if (props.disabled === true) {
    return
  }
  emit('select', stationId)
}
</script>

<template>
  <div class="agv-map">
    <div class="map-grid-bg"></div>
    <template v-for="station in stationList" :key="station.id">
      <button
        class="map-station"
        :class="{ 'map-station-active': props.currentStationId === station.id }"
        :style="{ left: `${station.x}%`, top: `${station.y}%` }"
        :disabled="props.disabled === true"
        :title="`${station.label} (${station.id}) - ${station.description}`"
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
}

.map-station:hover:not(:disabled) {
  transform: translate(-50%, -50%) scale(1.05);
  border-color: #1a75cf;
}

.map-station:disabled {
  cursor: not-allowed;
  opacity: 0.6;
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
