import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import { MANUAL_CONTENT, manualContent, visibleManual } from '../manual'
import { TOUR_CONTENT, findTour, tourForRoute } from '../tours'

/** Everything except the display text, which is the only thing allowed to differ per locale. */
function manualShape(locale: keyof typeof MANUAL_CONTENT) {
  const { sections, faq } = MANUAL_CONTENT[locale]
  return {
    sections: sections.map(({ id, icon, permission, route, tourKey, topics }) => ({
      id,
      icon,
      permission,
      route,
      tourKey,
      topics: topics.map(({ permission, steps }) => ({
        permission,
        steps: steps.map((s) => s.permission ?? null),
      })),
    })),
    faq: faq.map((f) => f.permission ?? null),
  }
}

function tourShape(locale: keyof typeof TOUR_CONTENT) {
  return TOUR_CONTENT[locale].map(({ key, version, routeName, permission, steps }) => ({
    key,
    version,
    routeName,
    permission,
    steps: steps.map(({ target, placement, permission }) => ({ target, placement, permission })),
  }))
}

describe('guide content per locale', () => {
  afterEach(() => {
    i18n.global.locale.value = 'zh-CN'
  })

  it('manual has the same structure in zh-CN and en', () => {
    expect(manualShape('en')).toEqual(manualShape('zh-CN'))
  })

  it('tours have the same structure in zh-CN and en', () => {
    expect(tourShape('en')).toEqual(tourShape('zh-CN'))
  })

  it('every manual tourKey points to an existing tour', () => {
    const keys = new Set(TOUR_CONTENT['zh-CN'].map((t) => t.key))
    for (const s of MANUAL_CONTENT['zh-CN'].sections) {
      if (s.tourKey) expect(keys.has(s.tourKey), s.id).toBe(true)
    }
  })

  it('has no empty text in either locale', () => {
    for (const locale of ['zh-CN', 'en'] as const) {
      const { sections, faq } = MANUAL_CONTENT[locale]
      const texts = [
        ...sections.flatMap((s) => [
          s.title,
          s.summary,
          ...s.topics.flatMap((t) => [t.title, ...t.steps.flatMap((st) => [st.title, st.detail])]),
        ]),
        ...faq.flatMap((f) => [f.question, f.answer]),
        ...TOUR_CONTENT[locale].flatMap((t) => [
          t.title,
          ...t.steps.flatMap((s) => [s.title, s.description]),
        ]),
      ]
      expect(
        texts.every((x) => x.trim() !== ''),
        locale,
      ).toBe(true)
    }
  })

  it('follows the current locale at call time', () => {
    i18n.global.locale.value = 'en'
    expect(manualContent()).toBe(MANUAL_CONTENT.en)
    expect(visibleManual(() => true).sections[0]!.title).toBe(MANUAL_CONTENT.en.sections[0]!.title)
    expect(findTour('search')).toBe(TOUR_CONTENT.en.find((t) => t.key === 'search'))
    expect(tourForRoute('search')?.title).toBe('Search tour')

    i18n.global.locale.value = 'zh-CN'
    expect(manualContent()).toBe(MANUAL_CONTENT['zh-CN'])
    expect(tourForRoute('search')?.title).toBe('搜索引导')
  })
})
