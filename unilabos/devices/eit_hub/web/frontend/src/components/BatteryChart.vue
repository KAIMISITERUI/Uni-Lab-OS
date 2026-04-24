<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { BatteryHistoryRecord } from '../api/agv'

echarts.use([
  LineChart,
  GridComponent,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    records: BatteryHistoryRecord[]
    hours: number
  }>(),
  {
    hours: 6,
  },
)

const chartContainer = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

function buildChartOption() {
  const points = props.records.map((record) => [record.timestamp, record.battery_level * 100])
  const chargingSpans = buildChargingSpans(props.records)
  const markAreaData = chargingSpans.map((span) => [
    { xAxis: span.start, itemStyle: { color: 'rgba(26, 117, 207, 0.12)' } },
    { xAxis: span.end },
  ])

  return {
    grid: { top: 40, right: 24, bottom: 40, left: 48 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const list = params as Array<{ axisValueLabel: string; value: [string, number] }>
        if (list.length === 0) {
          return ''
        }
        const point = list[0]
        return `${point.axisValueLabel}<br/>电量: ${point.value[1].toFixed(1)} %`
      },
    },
    xAxis: {
      type: 'time',
      boundaryGap: false,
      axisLabel: { color: '#66758a', fontSize: 11 },
      axisLine: { lineStyle: { color: '#dce5f0' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#66758a', fontSize: 11, formatter: '{value} %' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [
      {
        name: '电量',
        type: 'line',
        showSymbol: false,
        smooth: true,
        sampling: 'lttb',
        data: points,
        lineStyle: { color: '#1a75cf', width: 2 },
        areaStyle: { color: 'rgba(26, 117, 207, 0.15)' },
        markArea: markAreaData.length > 0 ? { silent: true, data: markAreaData } : undefined,
      },
    ],
  }
}

function buildChargingSpans(records: BatteryHistoryRecord[]) {
  const spans: Array<{ start: string; end: string }> = []
  let currentStart: string | null = null
  for (let i = 0; i < records.length; i += 1) {
    const rec = records[i]
    if (rec.charging === true && currentStart === null) {
      currentStart = rec.timestamp
    } else if (rec.charging === false && currentStart !== null) {
      spans.push({ start: currentStart, end: rec.timestamp })
      currentStart = null
    }
  }
  if (currentStart !== null && records.length > 0) {
    spans.push({ start: currentStart, end: records[records.length - 1].timestamp })
  }
  return spans
}

function renderChart() {
  if (chartInstance === null) {
    return
  }
  chartInstance.setOption(buildChartOption(), { notMerge: true })
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  if (chartContainer.value !== null) {
    chartInstance = echarts.init(chartContainer.value)
    renderChart()
    window.addEventListener('resize', handleResize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(
  () => [props.records, props.hours],
  () => renderChart(),
  { deep: true },
)
</script>

<template>
  <div ref="chartContainer" class="battery-chart"></div>
</template>

<style scoped>
.battery-chart {
  width: 100%;
  height: 240px;
}
</style>
