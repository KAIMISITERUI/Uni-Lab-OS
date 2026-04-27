import { createI18n } from 'vue-i18n'

const LANGUAGE_ZH = 'zh'
const LANGUAGE_EN = 'en'

export function getBrowserLanguage (): string {
  const _lang = window.navigator.language.split('-')[0]
  return _lang === 'zh' ? LANGUAGE_ZH : LANGUAGE_EN
}

export function getParamLanguage () : string {
  return window.webb.store?.get?.('params')?.$lang as string
}

export async function createI18nPlugin (): Promise<any> {
  const staticBaseUrl = 'http://localhost:9191/resource'
  const url = `${staticBaseUrl}/i18n/index.js`
  const i18nConfig = await eval(`import('${url}')`) as any
  const { staticLanguage, auto, enJson, zhJson } = i18nConfig
  const language = getParamLanguage() || staticLanguage || (auto ? getBrowserLanguage() : LANGUAGE_ZH)
  const i18n = createI18n({
    legacy: false,
    locale: language,
    globalInjection: true,
    messages: {
      en: enJson as Record<string, string>,
      zh: zhJson as Record<string, string>
    }
  })
  return i18n
}
