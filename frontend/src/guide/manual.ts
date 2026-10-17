import type { PermissionRequirement } from '@/utils/permission'
import { currentLocale, type AppLocale } from '@/i18n'
import * as en from './content/manual.en'
import * as zhCN from './content/manual.zh-CN'

export interface ManualStep {
  title: string
  detail: string
  /** Only shown to users holding one of these permissions. */
  permission?: PermissionRequirement
}

export interface ManualTopic {
  title: string
  permission?: PermissionRequirement
  steps: ManualStep[]
}

export interface ManualSection {
  id: string
  title: string
  icon: string
  summary: string
  permission?: PermissionRequirement
  /** Page opened by the "try it" button. */
  route?: string
  /** Tour played by the "play tour" button. */
  tourKey?: string
  topics: ManualTopic[]
}

export interface ManualFaq {
  question: string
  answer: string
  permission?: PermissionRequirement
}

export interface ManualContent {
  sections: ManualSection[]
  faq: ManualFaq[]
}

/** Same ids, permissions, routes and tours in every locale; only the text differs. */
export const MANUAL_CONTENT: Record<AppLocale, ManualContent> = {
  'zh-CN': { sections: zhCN.MANUAL_SECTIONS, faq: zhCN.MANUAL_FAQ },
  en: { sections: en.MANUAL_SECTIONS, faq: en.MANUAL_FAQ },
}

/** Manual for the current UI locale; reactive when read inside a computed or render. */
export function manualContent(locale: AppLocale = currentLocale()): ManualContent {
  return MANUAL_CONTENT[locale] ?? MANUAL_CONTENT['zh-CN']
}

/** Sections, topics, steps and FAQ entries the user is allowed to see. */
export function visibleManual(
  can: (required: PermissionRequirement | undefined) => boolean,
  locale: AppLocale = currentLocale(),
): ManualContent {
  const content = manualContent(locale)
  const sections = content.sections
    .filter((s) => can(s.permission))
    .map((s) => ({
      ...s,
      topics: s.topics
        .filter((t) => can(t.permission))
        .map((t) => ({ ...t, steps: t.steps.filter((st) => can(st.permission)) }))
        .filter((t) => t.steps.length > 0),
    }))
    .filter((s) => s.topics.length > 0)
  return { sections, faq: content.faq.filter((f) => can(f.permission)) }
}
