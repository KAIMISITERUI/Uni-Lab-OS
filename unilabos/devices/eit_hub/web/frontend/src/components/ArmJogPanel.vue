<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { armStop } from '../api/agv'
import { getErrorMessage } from '../api/http'
import {
  acquireDucoWs,
  moveJog as ducoMoveJog,
  releaseDucoWs,
  stopManualMove as ducoStopManualMove,
} from '../api/ducoWs'

type RefCoord = 'base' | 'tcp' | 'user'
type JogMode = 'continuous' | 'step'

interface JogBarItem {
  key: string
  label: string
  value: string
  minusDirection: string
  plusDirection: string
  accent: string
}

const props = withDefaults(
  defineProps<{
    disabled?: boolean
    tcpPose?: number[] | null
    joints?: number[] | null
  }>(),
  {
    disabled: false,
    tcpPose: null,
    joints: null,
  },
)

const refCoord = ref<RefCoord>('base')
const mode = ref<JogMode>('continuous')
const stepMm = ref(1.0)
const stepRad = ref(0.01)
const speed = ref(0.1)

const activeDirection = ref<string>('')
const activePointerId = ref<number | null>(null)
const activeElement = ref<HTMLElement | null>(null)
const isStepping = ref(false)

const panelBusy = computed(() => props.disabled === true)

const modeText = computed(() => {
  return mode.value === 'continuous' ? '连续模式' : '步进模式'
})

const refCoordText = computed(() => {
  if (refCoord.value === 'base') {
    return 'Base'
  }
  if (refCoord.value === 'tcp') {
    return 'TCP'
  }
  return 'User'
})

const jointRows = computed<JogBarItem[]>(() => {
  return Array.from({ length: 6 }, (_value, index) => {
    return {
      key: `joint-${index + 1}`,
      label: `关节 ${index + 1}`,
      value: formatJointValue(props.joints, index),
      minusDirection: `j${index + 1}-`,
      plusDirection: `j${index + 1}+`,
      accent: 'joint-accent',
    }
  })
})

const tcpRotateRows = computed<JogBarItem[]>(() => {
  return [
    { key: 'tcp-rx', label: 'RX', index: 3, minusDirection: 'rx-', plusDirection: 'rx+', accent: 'rx-accent' },
    { key: 'tcp-ry', label: 'RY', index: 4, minusDirection: 'ry-', plusDirection: 'ry+', accent: 'ry-accent' },
    { key: 'tcp-rz', label: 'RZ', index: 5, minusDirection: 'rz-', plusDirection: 'rz+', accent: 'rz-accent' },
  ].map((item) => {
    return {
      key: item.key,
      label: item.label,
      value: formatTcpValue(props.tcpPose, item.index),
      minusDirection: item.minusDirection,
      plusDirection: item.plusDirection,
      accent: item.accent,
    }
  })
})

const tcpTranslateRows = computed<JogBarItem[]>(() => {
  return [
    { key: 'tcp-x', label: 'X', index: 0, minusDirection: 'x-', plusDirection: 'x+', accent: 'x-accent' },
    { key: 'tcp-y', label: 'Y', index: 1, minusDirection: 'y-', plusDirection: 'y+', accent: 'y-accent' },
    { key: 'tcp-z', label: 'Z', index: 2, minusDirection: 'z-', plusDirection: 'z+', accent: 'z-accent' },
  ].map((item) => {
    return {
      key: item.key,
      label: item.label,
      value: formatTcpValue(props.tcpPose, item.index),
      minusDirection: item.minusDirection,
      plusDirection: item.plusDirection,
      accent: item.accent,
    }
  })
})

function formatJointValue(joints: number[] | null | undefined, index: number): string {
  if (joints === null || joints === undefined || joints.length <= index) {
    return '--'
  }
  return `${((joints[index] * 180) / Math.PI).toFixed(2)}°`
}

function formatTcpValue(pose: number[] | null | undefined, index: number): string {
  if (pose === null || pose === undefined || pose.length <= index) {
    return '--'
  }
  if (index < 3) {
    return pose[index].toFixed(3)
  }
  return `${((pose[index] * 180) / Math.PI).toFixed(2)}°`
}

function buildJogPayload(direction: string, useStep: boolean) {
  return {
    direction,
    refCoord: refCoord.value,
    useStep,
    stepMm: stepMm.value,
    stepRad: stepRad.value,
    speed: speed.value,
  }
}

function isActive(direction: string): boolean {
  return activeDirection.value === direction
}

function capturePointer(event: PointerEvent) {
  const element = event.currentTarget as HTMLElement | null
  if (element !== null) {
    try {
      element.setPointerCapture(event.pointerId)
    } catch {
      // 某些浏览器场景下可能无法捕获, 忽略即可.
    }
  }
  activePointerId.value = event.pointerId
  activeElement.value = element
}

function releasePointer() {
  const element = activeElement.value
  const pointerId = activePointerId.value
  if (element !== null && pointerId !== null) {
    try {
      if (element.hasPointerCapture(pointerId) === true) {
        element.releasePointerCapture(pointerId)
      }
    } catch {
      // 元素已失活时释放可能抛错, 忽略即可.
    }
  }
  activePointerId.value = null
  activeElement.value = null
}

function resetInteraction() {
  releasePointer()
  activeDirection.value = ''
}

function isSamePointer(event: PointerEvent): boolean {
  return activePointerId.value === null || activePointerId.value === event.pointerId
}

function handleStep(direction: string) {
  if (props.disabled === true || mode.value !== 'step') {
    return
  }

  activeDirection.value = direction
  isStepping.value = true
  ducoMoveJog(buildJogPayload(direction, true))
  // 步进没有明确的结束回包, 200ms 后清视觉高亮, 与单次帧发送时间匹配
  window.setTimeout(() => {
    isStepping.value = false
    activeDirection.value = ''
  }, 200)
}

function handleContinuousPress(direction: string, event: PointerEvent) {
  if (props.disabled === true || mode.value !== 'continuous') {
    return
  }

  event.preventDefault()
  capturePointer(event)
  const previous = activeDirection.value
  activeDirection.value = direction
  // 换向: 已有方向则先发 stop 再发 start, 保持与官方控制台一致的后到者胜语义
  if (previous !== '' && previous !== direction) {
    ducoStopManualMove()
  }
  ducoMoveJog(buildJogPayload(direction, false))
}

function requestStop() {
  releasePointer()
  if (activeDirection.value === '') {
    return
  }
  activeDirection.value = ''
  ducoStopManualMove()
}

function handleContinuousRelease(event: PointerEvent) {
  if (mode.value !== 'continuous' || isSamePointer(event) === false) {
    return
  }
  requestStop()
}

function handleLostPointerCapture(event: PointerEvent) {
  if (mode.value !== 'continuous' || isSamePointer(event) === false) {
    return
  }
  requestStop()
}

async function handleEmergencyStop() {
  releasePointer()
  activeDirection.value = ''
  ducoStopManualMove()
  try {
    await armStop()
    ElMessage.success('已发送停止指令')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    isStepping.value = false
  }
}

function handleVisibilityChange() {
  if (document.hidden === true && activeDirection.value !== '') {
    requestStop()
  }
}

function handleWindowBlur() {
  if (activeDirection.value !== '') {
    requestStop()
  }
}

function handlePageHide() {
  if (activeDirection.value !== '') {
    ducoStopManualMove()
  }
}

onMounted(() => {
  acquireDucoWs()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('blur', handleWindowBlur)
  window.addEventListener('pagehide', handlePageHide)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('blur', handleWindowBlur)
  window.removeEventListener('pagehide', handlePageHide)
  if (activeDirection.value !== '') {
    ducoStopManualMove()
  }
  resetInteraction()
  releaseDucoWs()
})

defineExpose<{
  emergencyStop: () => Promise<void>
}>({
  emergencyStop: handleEmergencyStop,
})
</script>

<template>
  <div class="arm-jog-panel">
    <div class="movement-shell">
      <div class="top-toolbar">
        <div class="toolbar-icons">
          <div class="tool-chip tool-chip-active">点动</div>
          <div class="tool-chip">{{ modeText }}</div>
          <div class="tool-chip">速度 {{ speed.toFixed(2) }}</div>
        </div>

        <div class="toolbar-controls">
          <el-select v-model="refCoord" size="small" class="coord-select" :disabled="panelBusy">
            <el-option label="参考坐标系: Base" value="base" />
            <el-option label="参考坐标系: TCP" value="tcp" />
            <el-option label="参考坐标系: User" value="user" />
          </el-select>

          <el-radio-group v-model="mode" size="small" :disabled="panelBusy">
            <el-radio-button label="continuous">连续</el-radio-button>
            <el-radio-button label="step">步进</el-radio-button>
          </el-radio-group>

          <el-button type="danger" size="small" @click="handleEmergencyStop">立即停止</el-button>
        </div>
      </div>

      <div class="value-toolbar">
        <div class="toolbar-card">
          <div class="toolbar-title">步进参数</div>
          <div class="toolbar-param">
            <span class="param-name">平移</span>
            <el-input-number v-model="stepMm" :min="0.1" :max="50" :step="0.5" :disabled="panelBusy" />
            <span class="param-unit">mm</span>
          </div>
          <div class="toolbar-param">
            <span class="param-name">旋转</span>
            <el-input-number
              v-model="stepRad"
              :min="0.001"
              :max="1"
              :step="0.005"
              :precision="3"
              :disabled="panelBusy"
            />
            <span class="param-unit">rad</span>
          </div>
        </div>

        <div class="toolbar-card">
          <div class="toolbar-title">当前模式</div>
          <div class="toolbar-meta">{{ modeText }}</div>
          <div class="toolbar-meta">参考系 {{ refCoordText }}</div>
        </div>
      </div>

      <div class="panel-layout">
        <section class="joint-panel">
          <div class="panel-caption">关节点动</div>
          <div class="joint-list">
            <div v-for="item in jointRows" :key="item.key" class="joint-row">
              <button
                class="side-btn"
                :class="{ active: isActive(item.minusDirection) }"
                :disabled="props.disabled === true"
                @click.prevent="handleStep(item.minusDirection)"
                @pointerdown="handleContinuousPress(item.minusDirection, $event)"
                @pointerup.prevent="handleContinuousRelease($event)"
                @pointercancel.prevent="handleContinuousRelease($event)"
                @lostpointercapture="handleLostPointerCapture($event)"
              >
                -
              </button>

              <div class="value-rail">
                <span class="axis-pill" :class="item.accent">{{ item.label }}</span>
                <span class="axis-value">{{ item.value }}</span>
              </div>

              <button
                class="side-btn"
                :class="{ active: isActive(item.plusDirection) }"
                :disabled="props.disabled === true"
                @click.prevent="handleStep(item.plusDirection)"
                @pointerdown="handleContinuousPress(item.plusDirection, $event)"
                @pointerup.prevent="handleContinuousRelease($event)"
                @pointercancel.prevent="handleContinuousRelease($event)"
                @lostpointercapture="handleLostPointerCapture($event)"
              >
                +
              </button>
            </div>
          </div>
        </section>

        <section class="tcp-panel">
          <div class="panel-caption">TCP 点动</div>
          <div class="tcp-grid">
            <div class="tcp-column">
              <div v-for="item in tcpRotateRows" :key="item.key" class="tcp-row">
                <button
                  class="side-btn"
                  :class="{ active: isActive(item.minusDirection) }"
                  :disabled="props.disabled === true"
                  @click.prevent="handleStep(item.minusDirection)"
                  @pointerdown="handleContinuousPress(item.minusDirection, $event)"
                  @pointerup.prevent="handleContinuousRelease($event)"
                  @pointercancel.prevent="handleContinuousRelease($event)"
                  @lostpointercapture="handleLostPointerCapture($event)"
                >
                  -
                </button>

                <div class="value-rail">
                  <span class="axis-pill" :class="item.accent">{{ item.label }}</span>
                  <span class="axis-value">{{ item.value }}</span>
                </div>

                <button
                  class="side-btn"
                  :class="{ active: isActive(item.plusDirection) }"
                  :disabled="props.disabled === true"
                  @click.prevent="handleStep(item.plusDirection)"
                  @pointerdown="handleContinuousPress(item.plusDirection, $event)"
                  @pointerup.prevent="handleContinuousRelease($event)"
                  @pointercancel.prevent="handleContinuousRelease($event)"
                  @lostpointercapture="handleLostPointerCapture($event)"
                >
                  +
                </button>
              </div>
            </div>

            <div class="tcp-column">
              <div v-for="item in tcpTranslateRows" :key="item.key" class="tcp-row">
                <button
                  class="side-btn"
                  :class="{ active: isActive(item.minusDirection) }"
                  :disabled="props.disabled === true"
                  @click.prevent="handleStep(item.minusDirection)"
                  @pointerdown="handleContinuousPress(item.minusDirection, $event)"
                  @pointerup.prevent="handleContinuousRelease($event)"
                  @pointercancel.prevent="handleContinuousRelease($event)"
                  @lostpointercapture="handleLostPointerCapture($event)"
                >
                  -
                </button>

                <div class="value-rail">
                  <span class="axis-pill" :class="item.accent">{{ item.label }}</span>
                  <span class="axis-value">{{ item.value }}</span>
                </div>

                <button
                  class="side-btn"
                  :class="{ active: isActive(item.plusDirection) }"
                  :disabled="props.disabled === true"
                  @click.prevent="handleStep(item.plusDirection)"
                  @pointerdown="handleContinuousPress(item.plusDirection, $event)"
                  @pointerup.prevent="handleContinuousRelease($event)"
                  @pointercancel.prevent="handleContinuousRelease($event)"
                  @lostpointercapture="handleLostPointerCapture($event)"
                >
                  +
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="pose-card">
        <div class="pose-line">
          <span class="pose-title">TCP</span>
          <span class="pose-value">
            {{ props.tcpPose === null || props.tcpPose === undefined ? '--' : props.tcpPose.map((value, index) => index < 3 ? value.toFixed(3) : `${((value * 180) / Math.PI).toFixed(2)}°`).join('  ') }}
          </span>
        </div>
        <div class="pose-line">
          <span class="pose-title">关节</span>
          <span class="pose-value">
            {{ props.joints === null || props.joints === undefined ? '--' : props.joints.map((value, index) => `J${index + 1}: ${((value * 180) / Math.PI).toFixed(2)}°`).join('  ') }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.arm-jog-panel {
  display: grid;
}

.movement-shell {
  display: grid;
  gap: 14px;
  padding: 12px;
  background: #eef2f7;
  border: 1px solid #d7e0eb;
  border-radius: 16px;
}

.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-icons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-chip {
  padding: 6px 10px;
  color: #55677f;
  font-size: 12px;
  background: #ffffff;
  border: 1px solid #d5ddea;
  border-radius: 8px;
}

.tool-chip-active {
  color: #ffffff;
  background: linear-gradient(135deg, #5176b8 0%, #365e9f 100%);
  border-color: #365e9f;
}

.toolbar-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.coord-select {
  min-width: 200px;
}

.value-toolbar {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) minmax(220px, 1fr);
  gap: 12px;
}

.toolbar-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  min-height: 58px;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 12px;
}

.toolbar-title {
  color: #2b3a4f;
  font-size: 13px;
  font-weight: 700;
}

.toolbar-param {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-name,
.param-unit,
.toolbar-meta {
  color: #5d6d83;
  font-size: 12px;
}

.panel-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.95fr) minmax(420px, 1.35fr);
  gap: 14px;
}

.joint-panel,
.tcp-panel {
  padding: 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 14px;
}

.panel-caption {
  margin-bottom: 12px;
  color: #2b3a4f;
  font-size: 13px;
  font-weight: 700;
}

.joint-list,
.tcp-column {
  display: grid;
  gap: 10px;
}

.joint-row,
.tcp-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 40px;
  gap: 10px;
  align-items: center;
}

.tcp-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.side-btn {
  width: 40px;
  height: 40px;
  color: #50627b;
  font-size: 22px;
  line-height: 1;
  background: #ffffff;
  border: 1px solid #cfd8e4;
  border-radius: 999px;
  box-shadow: 0 1px 3px rgba(28, 42, 61, 0.08);
  cursor: pointer;
  user-select: none;
  touch-action: none;
}

.side-btn.active {
  color: #ffffff;
  background: linear-gradient(135deg, #5176b8 0%, #365e9f 100%);
  border-color: #365e9f;
}

.side-btn:disabled {
  color: #a0acba;
  background: #f7f8fa;
  border-color: #dfe5ec;
  cursor: not-allowed;
}

.value-rail {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 0 52px;
  color: #243244;
  font-size: 13px;
  font-weight: 600;
  background: linear-gradient(180deg, #f7f7f8 0%, #efefef 100%);
  border: 1px solid #e3e6eb;
  border-radius: 999px;
}

.axis-pill {
  position: absolute;
  left: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 30px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
  border-radius: 999px;
}

.axis-value {
  text-align: center;
  white-space: nowrap;
}

.joint-accent {
  color: #586a84;
  background: #eef3fa;
}

.rx-accent {
  color: #df5948;
  background: #ffe3df;
}

.ry-accent {
  color: #2b9d5e;
  background: #dff6e8;
}

.rz-accent {
  color: #5576d9;
  background: #e3e9ff;
}

.x-accent {
  color: #df5948;
  background: #ffe3df;
}

.y-accent {
  color: #2b9d5e;
  background: #dff6e8;
}

.z-accent {
  color: #5576d9;
  background: #e3e9ff;
}

.pose-card {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 12px;
}

.pose-line {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.pose-title {
  min-width: 40px;
  color: #2b3a4f;
  font-size: 12px;
  font-weight: 700;
}

.pose-value {
  color: #34445d;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

@media (max-width: 1200px) {
  .panel-layout {
    grid-template-columns: 1fr;
  }

  .value-toolbar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .tcp-grid {
    grid-template-columns: 1fr;
  }

  .top-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-controls {
    justify-content: flex-start;
  }
}
</style>
