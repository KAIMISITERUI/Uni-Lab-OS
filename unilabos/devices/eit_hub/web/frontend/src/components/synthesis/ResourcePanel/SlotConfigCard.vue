<template>
  <!--
    功能:
      单个选中槽位的资源配置卡片. 三列布局:
        [左 缩略图+表单 220px] [中 孔位网格 auto] [右 物质表格 1fr]
      物料/Tip 托盘 (editSubstanceCreate=false) 不显示物质表格列, 仅左+中两列.
      未选托盘型号时, 中/右列显示提示占位, 不再折叠卡片.
  -->
  <div class="slot-card">
    <div class="card-header">
      <span class="layout-code">{{ config.layoutCode }}</span>
      <el-button v-if="!readonlyTrayModel" link type="danger" size="small" @click="emit('remove')">移除位置</el-button>
    </div>
    <div class="card-body">
      <div class="top-row" :class="{ 'has-editor': showVesselEditor }">
        <div class="left-col">
          <TrayThumbnail
            :tray-model="config.trayModel"
            :wells="config.wells"
            :layout-code="config.layoutCode"
          />
          <el-form label-position="top" size="small" class="tray-form">
            <el-form-item label="托盘类型" required>
              <el-select
                :model-value="config.trayModel"
                filterable
                :disabled="readonlyTrayModel"
                placeholder="请选择托盘型号"
                style="width: 100%"
                popper-class="resource-tray-model-popper"
                @update:model-value="onTrayModelChange"
              >
                <el-option
                  v-for="opt in trayOptions"
                  :key="opt.model"
                  :label="`${opt.name} (${opt.model})`"
                  :value="opt.model"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="托盘条码">
              <el-input
                :model-value="config.trayQRCode"
                placeholder="请扫码"
                @update:model-value="(v: string) => emit('update:tray-qr', v)"
              />
            </el-form-item>
          </el-form>
        </div>
        <div class="grid-col">
          <WellGrid
            v-if="trayOption"
            :key="config.trayModel"
            :row="trayOption.row"
            :col="trayOption.col"
            :wells="config.wells"
            :allow-disabled="allowDisabled"
            @update:wells="(v) => emit('update:wells', v)"
          />
          <el-empty v-else description="请先选择托盘型号" :image-size="60" />
        </div>
        <div v-if="showVesselEditor" class="editor-col">
          <VesselEditor
            :wells="config.wells"
            @update:wells="(v) => emit('update:wells', v)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SelectedSlotConfig, TrayModelOption, WellInfo } from './types'
import WellGrid from './WellGrid.vue'
import TrayThumbnail from './TrayThumbnail.vue'
import VesselEditor from './VesselEditor.vue'

interface Props {
  config: SelectedSlotConfig
  trayOptions: TrayModelOption[]
  // 编辑模式: 托盘型号只读 + 隐藏移除位置按钮
  readonlyTrayModel?: boolean
  // 编辑模式: WellGrid 三态 (empty/filled/disabled)
  allowDisabled?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  readonlyTrayModel: false,
  allowDisabled: false,
})
const emit = defineEmits<{
  (e: 'remove'): void
  (e: 'update:tray-model', val: string): void
  (e: 'update:tray-qr', val: string): void
  (e: 'update:wells', val: WellInfo[]): void
}>()

const trayOption = computed<TrayModelOption | undefined>(() =>
  props.trayOptions.find((t) => t.model === props.config.trayModel),
)

// 仅试剂托盘 (editSubstance.create=true) 显示物质表格;
// 物料/Tip 托盘 (editSubstanceCreate=false) 不暴露物质字段
const showVesselEditor = computed(() => {
  if (!trayOption.value) { return false }
  return trayOption.value.editSubstanceCreate === true
})

function onTrayModelChange (val: string): void {
  emit('update:tray-model', val)
}
</script>

<style>
.resource-tray-model-popper {
  z-index: 6000 !important;
}
</style>

<style scoped>
.slot-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fff;
  margin-bottom: 12px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #f2f2f2;
  background: #fafbfc;
  border-top-left-radius: 6px;
  border-top-right-radius: 6px;
}
.card-header .layout-code {
  font-weight: 600;
  color: #4a86ff;
  font-size: 14px;
}
.card-body {
  padding: 12px 14px 14px;
}
.top-row {
  display: grid;
  grid-template-columns: 220px auto;
  gap: 14px;
  align-items: start;
}
.top-row.has-editor {
  /* 试剂托盘 启用第三列 物质表 */
  grid-template-columns: 220px auto 1fr;
}
.left-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.grid-col {
  min-width: 0;
  display: flex;
  justify-content: flex-start;
}
.editor-col {
  min-width: 0;
}
.tray-form :deep(.el-form-item) {
  margin-bottom: 8px;
}
</style>
