<script setup lang="ts">
import { computed } from 'vue'
import type { ChemicalRow, HazardStatement } from '../api/chemicals'

/**
 * 功能:
 *     展示化学品 GHS 危害摘要或详情.
 * 参数:
 *     chemical 化学品行数据.
 *     mode summary 用于表格和编辑弹窗, detail 用于详情弹窗.
 */
interface Props {
  chemical: Partial<ChemicalRow> | null
  mode?: 'summary' | 'detail'
  summaryPart?: 'combined' | 'level' | 'content'
}

const props = withDefaults(defineProps<Props>(), {
  mode: 'summary',
  summaryPart: 'combined',
})

const highRiskCodes = new Set(['H340', 'H350', 'H350I', 'H360', 'H370', 'H372'])

const pictogramLabels: Record<string, string> = {
  GHS01: '爆炸物',
  GHS02: '易燃',
  GHS03: '氧化剂',
  GHS04: '气体压力',
  GHS05: '腐蚀',
  GHS06: '急性毒性',
  GHS07: '刺激性',
  GHS08: '健康危害',
  GHS09: '环境危害',
}

const hazardTranslations: Record<string, string> = {
  H225: '高度易燃液体和蒸气',
  H226: '易燃液体和蒸气',
  H228: '易燃固体',
  H301: '吞咽有毒',
  H302: '吞咽有害',
  H304: '吞咽并进入呼吸道可能致命',
  H311: '皮肤接触有毒',
  H312: '皮肤接触有害',
  H314: '造成严重皮肤灼伤和眼损伤',
  H315: '造成皮肤刺激',
  H317: '可能造成皮肤过敏反应',
  H318: '造成严重眼损伤',
  H319: '造成严重眼刺激',
  H330: '吸入致命',
  H331: '吸入有毒',
  H332: '吸入有害',
  H334: '吸入可能导致过敏或哮喘症状',
  H335: '可能造成呼吸道刺激',
  H336: '可能造成嗜睡或眩晕',
  H340: '可能导致遗传性缺陷',
  H341: '怀疑会导致遗传性缺陷',
  H350: '可能致癌',
  H350I: '吸入可能致癌',
  H351: '怀疑会致癌',
  H360: '可能损害生育能力或胎儿',
  H361: '怀疑损害生育能力或胎儿',
  H370: '会对器官造成损害',
  H371: '可能对器官造成损害',
  H372: '长期或反复暴露会对器官造成损害',
  H373: '长期或反复暴露可能对器官造成损害',
  H400: '对水生生物毒性极大',
  H410: '对水生生物毒性极大并具有长期持续影响',
  H411: '对水生生物有毒并具有长期持续影响',
  H412: '对水生生物有害并具有长期持续影响',
}

const precautionaryTranslations: Record<string, string> = {
  P203: '使用前取得, 阅读并遵循所有安全说明.',
  P210: '远离热源, 热表面, 火花, 明火和其他点火源. 禁止吸烟.',
  P233: '保持容器密闭.',
  P240: '容器和接收设备应接地并等电位连接.',
  P241: '使用防爆电气, 通风和照明设备.',
  P242: '使用不产生火花的工具.',
  P243: '采取措施防止静电放电.',
  P260: '避免吸入粉尘, 烟雾, 气体, 雾滴, 蒸气或喷雾.',
  P261: '避免吸入粉尘, 烟雾, 气体, 雾滴, 蒸气或喷雾.',
  P264: '操作后彻底清洗接触部位.',
  'P264+P265': '操作后彻底清洗接触部位. 不要触摸眼睛.',
  P270: '使用本品时不要进食, 饮水或吸烟.',
  P271: '只能在室外或通风良好处使用.',
  P273: '避免释放到环境中.',
  P280: '穿戴防护手套, 防护服, 护目镜或面部防护.',
  'P301+P316': '如误吞咽, 立即寻求紧急医疗帮助.',
  'P302+P352': '如皮肤接触, 用大量水清洗.',
  'P303+P361+P353': '如皮肤或头发接触, 立即脱去所有受污染衣物, 用水冲洗皮肤.',
  'P304+P340': '如误吸入, 将人员转移到空气新鲜处, 保持呼吸舒适体位.',
  'P305+P351+P338': '如进入眼睛, 用水小心冲洗数分钟. 如戴隐形眼镜且易于取出, 取出后继续冲洗.',
  P318: '如暴露或担心暴露, 立即获取医疗建议.',
  P319: '如感觉不适, 就医.',
  P321: '具体处理见产品标签或安全数据表.',
  P330: '漱口.',
  P331: '不要催吐.',
  'P332+P317': '如发生皮肤刺激, 就医.',
  'P337+P317': '如眼刺激持续, 就医.',
  'P362+P364': '脱去受污染衣物, 再次使用前清洗.',
  'P370+P378': '发生火灾时, 使用适合的灭火介质灭火.',
  P391: '收集泄漏物.',
  'P403+P235': '存放在通风良好处, 保持低温.',
  P405: '上锁存放.',
  P501: '按照法规处置内容物和容器.',
}

function asStringArray(value: unknown): string[] {
  if (Array.isArray(value) === false) {
    return []
  }
  return value
    .map((item) => String(item ?? '').trim())
    .filter((item) => item !== '')
}

function asStatements(value: unknown): HazardStatement[] {
  if (Array.isArray(value) === false) {
    return []
  }
  return value
    .filter((item): item is HazardStatement => {
      return typeof item === 'object' && item !== null && 'code' in item
    })
    .map((item) => ({
      ...item,
      code: String(item.code ?? '').trim(),
    }))
    .filter((item) => item.code !== '')
}

function normalizeCode(code: string): string {
  return code.trim().toUpperCase()
}

function statementText(item: HazardStatement): string {
  const code = normalizeCode(item.code)
  if (hazardTranslations[code] !== undefined) {
    return hazardTranslations[code]
  }
  return String(item.statement ?? item.raw ?? '').trim()
}

function ghsIconUrl(code: string): string {
  return `https://pubchem.ncbi.nlm.nih.gov/images/ghs/${code}.svg`
}

function precautionaryText(code: string): string {
  const normalizedCode = code.trim().toUpperCase()
  if (precautionaryTranslations[normalizedCode] !== undefined) {
    return precautionaryTranslations[normalizedCode]
  }

  const splitTexts = normalizedCode
    .split('+')
    .map((part) => precautionaryTranslations[part])
    .filter((text): text is string => text !== undefined)
  if (splitTexts.length > 0) {
    return splitTexts.join(' ')
  }
  return '请按产品标签或安全数据表执行对应防护措施.'
}

const pictograms = computed(() => asStringArray(props.chemical?.hazard_pictograms).map((item) => item.toUpperCase()))
const statements = computed(() => asStatements(props.chemical?.hazard_statements))
const precautionaryCodes = computed(() => asStringArray(props.chemical?.precautionary_codes))
const echaSummary = computed(() => asStringArray(props.chemical?.hazard_echa_summary))
const hazardSource = computed(() => String(props.chemical?.hazard_source ?? 'PubChem PUG-View'))
const sourceUrl = computed(() => String(props.chemical?.hazard_source_url ?? '').trim())
const precautionaryItems = computed(() => {
  return precautionaryCodes.value.map((code) => {
    const normalizedCode = code.trim().toUpperCase()
    return {
      code: normalizedCode,
      text: precautionaryText(normalizedCode),
    }
  })
})

const statementCodes = computed(() => statements.value.map((item) => normalizeCode(item.code)))

const hasHazard = computed(() => {
  return pictograms.value.length > 0 || statements.value.length > 0 || String(props.chemical?.hazard_signal ?? '').trim() !== ''
})

const isHighRisk = computed(() => {
  if (pictograms.value.includes('GHS08') === true) {
    return true
  }
  return statementCodes.value.some((code) => highRiskCodes.has(code))
})

const signalLabel = computed(() => {
  const signal = String(props.chemical?.hazard_signal ?? '').trim()
  if (signal === 'Danger') {
    return '危险'
  }
  if (signal === 'Warning') {
    return '警告'
  }
  return signal
})

const visibleHazardNames = computed(() => {
  const names: string[] = []
  statements.value.forEach((item) => {
    const text = statementText(item)
    if (text === '' || names.includes(text) === true) {
      return
    }
    names.push(text)
  })

  if (names.length === 0) {
    pictograms.value.forEach((code) => {
      const text = pictogramLabels[code] ?? code
      if (names.includes(text) === false) {
        names.push(text)
      }
    })
  }

  return names.slice(0, 3)
})
const hiddenHazardNameCount = computed(() => {
  const statementCount = statements.value.length
  const pictogramOnlyCount = statementCount === 0 ? pictograms.value.length : 0
  return Math.max(0, Math.max(statementCount, pictogramOnlyCount) - visibleHazardNames.value.length)
})

const groupedStatements = computed(() => {
  const groups = [
    { key: 'physical', title: '物理危害', items: [] as HazardStatement[] },
    { key: 'health', title: '健康危害', items: [] as HazardStatement[] },
    { key: 'environment', title: '环境危害', items: [] as HazardStatement[] },
    { key: 'other', title: '其他危害', items: [] as HazardStatement[] },
  ]

  statements.value.forEach((item) => {
    const code = normalizeCode(item.code)
    if (code.startsWith('H2') === true) {
      groups[0].items.push(item)
    } else if (code.startsWith('H3') === true) {
      groups[1].items.push(item)
    } else if (code.startsWith('H4') === true) {
      groups[2].items.push(item)
    } else {
      groups[3].items.push(item)
    }
  })

  return groups.filter((group) => group.items.length > 0)
})
</script>

<template>
  <div v-if="mode === 'summary'" class="hazard-summary" :class="{ 'is-high-risk': isHighRisk }">
    <span v-if="hasHazard === false" class="hazard-empty">未检索</span>
    <template v-else>
      <template v-if="summaryPart === 'combined' || summaryPart === 'level'">
        <span v-if="isHighRisk" class="risk-badge">高危</span>
        <span v-else-if="signalLabel !== ''" class="signal-badge">{{ signalLabel }}</span>
      </template>
      <span v-if="summaryPart === 'combined' || summaryPart === 'content'" class="hazard-name-row">
        <span
          v-for="name in visibleHazardNames"
          :key="name"
          class="hazard-name"
          :title="name"
        >
          {{ name }}
        </span>
        <span v-if="hiddenHazardNameCount > 0" class="hazard-name more">+{{ hiddenHazardNameCount }}</span>
      </span>
    </template>
  </div>

  <section v-else class="hazard-detail" :class="{ 'is-high-risk': isHighRisk }">
    <div class="hazard-detail-header">
      <div>
        <div class="hazard-title">安全危害</div>
        <div v-if="hasHazard" class="hazard-source">
          {{ hazardSource }}
          <a
            v-if="sourceUrl !== ''"
            :href="sourceUrl"
            target="_blank"
            rel="noreferrer"
          >
            查看来源
          </a>
        </div>
      </div>
      <span v-if="hasHazard && isHighRisk" class="risk-badge large">高危健康危害</span>
      <span v-else-if="hasHazard && signalLabel !== ''" class="signal-badge large">{{ signalLabel }}</span>
    </div>

    <div v-if="hasHazard === false" class="hazard-empty detail-empty">未检索到危害信息</div>
    <template v-else>
      <div class="pictogram-detail-row">
        <span v-for="code in pictograms" :key="code" class="pictogram-item">
          <img class="ghs-icon large" :src="ghsIconUrl(code)" :alt="pictogramLabels[code] ?? code">
          <span>{{ pictogramLabels[code] ?? code }}</span>
        </span>
      </div>

      <div v-for="group in groupedStatements" :key="group.key" class="hazard-group">
        <div class="group-title">{{ group.title }}</div>
        <div v-for="item in group.items" :key="item.code" class="statement-row">
          <span class="h-code">{{ item.code }}</span>
          <span class="statement-text">{{ statementText(item) }}</span>
          <span v-if="item.ratio" class="ratio-text">{{ item.ratio }}</span>
        </div>
      </div>

      <div v-if="precautionaryItems.length > 0" class="hazard-group">
        <div class="group-title">防护建议</div>
        <div class="precaution-list">
          <div v-for="item in precautionaryItems" :key="item.code" class="precaution-row">
            <span class="p-code">{{ item.code }}</span>
            <span class="precaution-text">{{ item.text }}</span>
          </div>
        </div>
      </div>

      <div v-if="echaSummary.length > 0" class="source-note">
        {{ echaSummary[0] }}
      </div>
    </template>
  </section>
</template>

<style scoped>
.hazard-summary {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  max-width: 100%;
  flex-wrap: wrap;
}

.hazard-empty {
  color: var(--el-text-color-placeholder);
}

.risk-badge,
.signal-badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.risk-badge {
  color: #9f1239;
  background: #ffe4e6;
  border: 1px solid #fecdd3;
}

.signal-badge {
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fde68a;
}

.risk-badge.large,
.signal-badge.large {
  height: 26px;
  font-size: 13px;
}

.hazard-name-row,
.code-row,
.pictogram-detail-row,
.code-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: center;
}

.hazard-name {
  display: inline-flex;
  align-items: center;
  max-width: 150px;
  min-height: 22px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.25;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.is-high-risk .hazard-name {
  color: #9f1239;
  background: #fff1f2;
  border-color: #fecdd3;
}

.hazard-name.more {
  font-weight: 600;
}

.ghs-icon {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.ghs-icon.large {
  width: 32px;
  height: 32px;
}

.h-code,
.p-code {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--el-font-family-mono, monospace);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-regular);
}

.is-high-risk .h-code {
  color: #9f1239;
  background: #fff1f2;
  border-color: #fecdd3;
}

.h-code.more {
  font-family: inherit;
}

.hazard-detail {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  font-size: 14px;
  line-height: 1.45;
  color: var(--el-text-color-regular);
}

.hazard-detail.is-high-risk {
  border-color: #fecdd3;
  background: #fff7f7;
}

.hazard-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.hazard-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.hazard-source {
  margin-top: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.hazard-source a {
  margin-left: 8px;
}

.detail-empty {
  padding: 10px 0 2px;
}

.pictogram-detail-row {
  justify-content: flex-start;
  margin-bottom: 10px;
}

.pictogram-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.hazard-group {
  margin-top: 10px;
}

.group-title {
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.statement-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 5px;
  line-height: 1.45;
}

.statement-text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.ratio-text {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.code-wrap {
  justify-content: flex-start;
}

.precaution-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.precaution-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.precaution-text {
  min-width: 0;
  color: var(--el-text-color-regular);
  word-break: break-word;
}

.source-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--el-text-color-secondary);
}
</style>
