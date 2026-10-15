import { get } from './http'
import type { MeResponse } from './types'

export function fetchMe(): Promise<MeResponse> {
  return get<MeResponse>('/auth/me')
}
