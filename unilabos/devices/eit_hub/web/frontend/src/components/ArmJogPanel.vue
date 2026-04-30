<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

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
    refCoord?: RefCoord
  }>(),
  {
    disabled: false,
    tcpPose: null,
    joints: null,
    refCoord: 'base',
  },
)

const mode = ref<JogMode>('continuous')
const stepMm = ref(1.0)
const stepRad = ref(0.01)
const speed = ref(0.1)

const activeDirection = ref<string>('')
const activePointerId = ref<number | null>(null)
const activeElement = ref<HTMLElement | null>(null)
const isStepping = ref(false)

const panelBusy = computed(() => props.disabled === true)

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
    refCoord: props.refCoord,
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

function handleEmergencyStop() {
  releasePointer()
  activeDirection.value = ''
  ducoStopManualMove()
  isStepping.value = false
  ElMessage.success('已发送停止指令')
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
  emergencyStop: () => void
}>({
  emergencyStop: handleEmergencyStop,
})
</script>

<template>
  <div class="arm-jog-panel">
    <div class="movement-shell">
      <div class="panel-layout">
        <div class="tcp-zone">
          <div class="tcp-toolbar">
            <el-radio-group v-model="mode" size="large" class="mode-switch" :disabled="panelBusy">
              <el-radio-button label="continuous">连续</el-radio-button>
              <el-radio-button label="step">步进</el-radio-button>
            </el-radio-group>

            <div class="toolbar-param">
              <span class="param-name">速度</span>
              <el-input-number
                v-model="speed"
                size="small"
                :min="0.01"
                :max="1"
                :step="0.05"
                :precision="2"
                :disabled="panelBusy"
              />
            </div>

            <template v-if="mode === 'step'">
              <div class="toolbar-param">
                <span class="param-name">平移</span>
                <el-input-number v-model="stepMm" size="small" :min="0.1" :max="50" :step="0.5" :disabled="panelBusy" />
                <span class="param-unit">mm</span>
              </div>
              <div class="toolbar-param">
                <span class="param-name">旋转</span>
                <el-input-number
                  v-model="stepRad"
                  size="small"
                  :min="0.001"
                  :max="1"
                  :step="0.005"
                  :precision="3"
                  :disabled="panelBusy"
                />
                <span class="param-unit">rad</span>
              </div>
            </template>
          </div>

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

.tcp-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: 14px;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 8px;
}

.mode-switch :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 84px;
  height: 42px;
  padding: 0 18px;
  font-size: 15px;
  font-weight: 700;
  line-height: 1;
}

.mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #1a5fa8;
  border-color: #1a5fa8;
  box-shadow: -1px 0 0 0 #1a5fa8;
}

.toolbar-param {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-param :deep(.el-input-number) {
  width: 132px;
}

.toolbar-param :deep(.el-input-number__decrease),
.toolbar-param :deep(.el-input-number__increase) {
  width: 36px;
}

.toolbar-param :deep(.el-input__wrapper) {
  min-height: 36px;
}

.toolbar-param :deep(.el-input__inner) {
  font-size: 13px;
  font-weight: 600;
}

.param-name,
.param-unit {
  color: #5d6d83;
  font-size: 13px;
  font-weight: 600;
}

.panel-layout {
  display: grid;
  grid-template-columns: minmax(520px, 1.35fr) minmax(300px, 0.8fr);
  gap: 14px;
  align-items: stretch;
}

.joint-panel,
.tcp-panel {
  padding: 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 14px;
}

.joint-panel {
  align-self: stretch;
}

.tcp-zone {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-content: start;
  align-self: stretch;
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
  display: flex;
  align-items: flex-start;
  flex-wrap: nowrap;
  column-gap: 48px;
  flex: 1;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #d7e0eb;
  border-radius: 12px;
  min-height: 92px;
  overflow-x: auto;
}

.pose-line {
  display: grid;
  flex: 0 0 max-content;
  gap: 4px;
  min-width: max-content;
  width: max-content;
}

.pose-title {
  color: #2b3a4f;
  font-size: 12px;
  font-weight: 700;
}

.pose-value {
  display: block;
  width: max-content;
  color: #34445d;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  overflow-x: visible;
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .panel-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .pose-card {
    flex-direction: column;
    row-gap: 8px;
  }

  .pose-line {
    min-width: 0;
    width: 100%;
  }

  .pose-value {
    overflow-x: auto;
  }

  .tcp-grid {
    grid-template-columns: 1fr;
  }

  .tcp-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
