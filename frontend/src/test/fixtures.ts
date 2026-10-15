import type { MeResponse } from '@/api/types'

export function makeProfile(
  permissions: string[],
  overrides: Partial<MeResponse> = {},
): MeResponse {
  return {
    id: 'u-1',
    username: 'alice',
    display_name: 'Alice',
    email: 'alice@example.com',
    org: {
      id: 'o-1',
      code: 'org-demo',
      name: 'Demo Org',
      status: 'active',
      created_at: '2026-01-01T00:00:00Z',
    },
    department: null,
    roles: [],
    groups: [],
    permissions,
    is_platform_admin: false,
    ...overrides,
  }
}
