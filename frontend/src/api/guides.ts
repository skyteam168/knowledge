import { del, get, put } from './http'
import type { GuideProgress, GuideStatus } from './types'

export const listGuideProgress = () => get<GuideProgress[]>('/me/guides', { silent: true })

export const saveGuideProgress = (key: string, version: number, status: GuideStatus) =>
  put<GuideProgress>(`/me/guides/${key}`, { version, status }, { silent: true })

export const resetGuideProgress = () => del<void>('/me/guides')
