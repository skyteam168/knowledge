import { computed, watch } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'

export const SUPPORTED_LOCALES = ['zh-CN', 'en'] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export const LOCALE_LABELS: Record<AppLocale, string> = {
  'zh-CN': '简体中文',
  en: 'English',
}

const STORAGE_KEY = 'ekb.locale'

export type LocaleMessages = { [key: string]: string | LocaleMessages }
export type LocaleModule = Record<AppLocale, LocaleMessages>

/**
 * Every `locales/<ns>.ts` exports `{ 'zh-CN': {...}, en: {...} }` and is mounted under `<ns>`,
 * so feature areas own their file and keys read as `t('<ns>.key')`.
 */
const modules = import.meta.glob<{ default: LocaleModule }>('./locales/*.ts', { eager: true })

export function localeModules(): Record<string, LocaleModule> {
  const result: Record<string, LocaleModule> = {}
  for (const [path, mod] of Object.entries(modules)) {
    result[path.replace(/^.*\/(.+)\.ts$/, '$1')] = mod.default
  }
  return result
}

function buildMessages(): Record<AppLocale, LocaleMessages> {
  const messages = { 'zh-CN': {}, en: {} } as Record<AppLocale, LocaleMessages>
  for (const [ns, mod] of Object.entries(localeModules())) {
    for (const locale of SUPPORTED_LOCALES) messages[locale][ns] = mod[locale]
  }
  return messages
}

export function isAppLocale(value: unknown): value is AppLocale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

function detectLocale(): AppLocale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isAppLocale(stored)) return stored
  } catch {
    /* storage unavailable */
  }
  const lang = typeof navigator !== 'undefined' ? navigator.language : ''
  return /^zh\b/i.test(lang) ? 'zh-CN' : 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: buildMessages(),
  missingWarn: false,
  fallbackWarn: false,
})

export function currentLocale(): AppLocale {
  return i18n.global.locale.value as AppLocale
}

export function setLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

/** For code outside components (stores, utils, API helpers). Call at use time, never at import. */
export function t(key: string, named?: Record<string, unknown>): string {
  return named ? i18n.global.t(key, named) : i18n.global.t(key)
}

/** Element Plus locale following the app locale (dates, pagination, empty states…). */
export const elementLocale = computed(() => (currentLocale() === 'en' ? en : zhCn))

watch(
  () => i18n.global.locale.value,
  (locale) => {
    if (typeof document !== 'undefined') document.documentElement.lang = locale
  },
  { immediate: true },
)
