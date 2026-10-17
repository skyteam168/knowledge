import type { PermissionRequirement } from '@/utils/permission'
import { currentLocale, type AppLocale } from '@/i18n'
import { TOURS as EN_TOURS } from './content/tours.en'
import { TOURS as ZH_CN_TOURS } from './content/tours.zh-CN'

export type TourPlacement = 'top' | 'bottom' | 'left' | 'right' | 'bottom-start' | 'right-start'

export interface TourStepDef {
  /** `data-guide` value of the highlighted element; omit for a centered card. */
  target?: string
  title: string
  description: string
  placement?: TourPlacement
  permission?: PermissionRequirement
}

export interface TourDef {
  key: string
  /** Bump to show the tour again to everyone after a significant UI change. */
  version: number
  title: string
  /** Route name whose first visit plays the tour; the layout tour has none. */
  routeName?: string
  permission?: PermissionRequirement
  steps: TourStepDef[]
}

export interface ResolvedStep {
  target?: string
  title: string
  description: string
  placement?: TourPlacement
}

export const LAYOUT_TOUR = 'layout'

/** Same keys, versions, routes, targets and step order in every locale; only the text differs. */
export const TOUR_CONTENT: Record<AppLocale, TourDef[]> = {
  'zh-CN': ZH_CN_TOURS,
  en: EN_TOURS,
}

/** Tours for the current UI locale; reactive when read inside a computed or render. */
export function tours(locale: AppLocale = currentLocale()): TourDef[] {
  return TOUR_CONTENT[locale] ?? TOUR_CONTENT['zh-CN']
}

export function findTour(key: string): TourDef | undefined {
  return tours().find((t) => t.key === key)
}

export function tourForRoute(routeName: unknown): TourDef | undefined {
  return typeof routeName === 'string' ? tours().find((t) => t.routeName === routeName) : undefined
}

export function guideSelector(target: string): string {
  return `[data-guide="${target}"]`
}

/** Indexes into `tour.steps` the user is allowed to see whose target is currently on the page. */
export function resolveStepIndexes(
  tour: TourDef,
  can: (required: PermissionRequirement | undefined) => boolean,
  exists: (target: string) => boolean = (t) => document.querySelector(guideSelector(t)) !== null,
): number[] {
  return tour.steps.flatMap((s, i) =>
    can(s.permission) && (!s.target || exists(s.target)) ? [i] : [],
  )
}

export function stepsAt(tour: TourDef, indexes: number[]): ResolvedStep[] {
  return indexes.flatMap((i) => {
    const step = tour.steps[i]
    if (!step) return []
    const { target, title, description, placement } = step
    return [{ target, title, description, placement }]
  })
}

/** Steps the user is allowed to see whose target is currently on the page. */
export function resolveSteps(
  tour: TourDef,
  can: (required: PermissionRequirement | undefined) => boolean,
  exists?: (target: string) => boolean,
): ResolvedStep[] {
  return stepsAt(tour, resolveStepIndexes(tour, can, exists))
}
