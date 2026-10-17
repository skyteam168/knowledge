import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '../index'
import { permissionName, roleName } from '../catalog'

afterEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

describe('catalog names', () => {
  it('translates built-in permissions and keeps unknown ones', () => {
    i18n.global.locale.value = 'en'
    expect(permissionName('admin:*', '全部管理权限')).toBe('All admin permissions')
    expect(permissionName('*', '超级权限')).toBe('Superuser')
    expect(permissionName('custom:x', '自定义')).toBe('自定义')
  })

  it('translates untouched system role names only', () => {
    i18n.global.locale.value = 'en'
    expect(roleName({ code: 'kb_admin', name: '知识库管理员' })).toBe('Knowledge base admin')
    expect(roleName({ code: 'kb_admin', name: 'IT 管理员' })).toBe('IT 管理员')
    expect(roleName({ code: 'custom', name: '车间主任' })).toBe('车间主任')
    i18n.global.locale.value = 'zh-CN'
    expect(roleName({ code: 'kb_viewer', name: '知识库只读用户' })).toBe('知识库只读用户')
  })
})
