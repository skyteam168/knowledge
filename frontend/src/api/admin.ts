import { del, get, post, put } from './http'
import type {
  AuditLog,
  AuditQuery,
  Department,
  DepartmentCreate,
  DepartmentNode,
  DepartmentUpdate,
  Group,
  GroupCreate,
  GroupUpdate,
  Page,
  PageParams,
  PasswordLoginOut,
  Permission,
  Role,
  RoleBulkAssign,
  RoleBulkResult,
  RoleCreate,
  RoleUpdate,
  User,
  UserCreate,
  UserDetail,
  UserQuery,
  UserUpdate,
} from './types'

// ---- departments ------------------------------------------------------------

export const getDepartmentTree = () => get<DepartmentNode[]>('/admin/departments/tree')
export const createDepartment = (body: DepartmentCreate) =>
  post<Department>('/admin/departments', body)
export const updateDepartment = (id: string, body: DepartmentUpdate) =>
  put<Department>(`/admin/departments/${id}`, body)
export const deleteDepartment = (id: string) => del<void>(`/admin/departments/${id}`)

// ---- users ------------------------------------------------------------------

export const listUsers = (params: UserQuery) => get<Page<User>>('/admin/users', { params })
export const getUser = (id: string) => get<UserDetail>(`/admin/users/${id}`)
export const createUser = (body: UserCreate) => post<User>('/admin/users', body)
export const updateUser = (id: string, body: UserUpdate) => put<User>(`/admin/users/${id}`, body)
export const disableUser = (id: string) => del<User>(`/admin/users/${id}`)
export const openPasswordLogin = (id: string) =>
  post<PasswordLoginOut>(`/admin/users/${id}/password-login`)
export const setUserRoles = (id: string, ids: string[]) =>
  put<UserDetail>(`/admin/users/${id}/roles`, { ids })
export const setUserGroups = (id: string, ids: string[]) =>
  put<UserDetail>(`/admin/users/${id}/groups`, { ids })

// ---- groups -----------------------------------------------------------------

export const listGroups = (params: PageParams & { keyword?: string }) =>
  get<Page<Group>>('/admin/groups', { params })
export const createGroup = (body: GroupCreate) => post<Group>('/admin/groups', body)
export const updateGroup = (id: string, body: GroupUpdate) =>
  put<Group>(`/admin/groups/${id}`, body)
export const deleteGroup = (id: string) => del<void>(`/admin/groups/${id}`)
export const getGroupMembers = (id: string) => get<User[]>(`/admin/groups/${id}/members`)
export const setGroupMembers = (id: string, ids: string[]) =>
  put<User[]>(`/admin/groups/${id}/members`, { ids })

// ---- roles & permissions ------------------------------------------------------

export const listRoles = () => get<Role[]>('/admin/roles')
export const listPermissions = () => get<Permission[]>('/admin/permissions')
export const createRole = (body: RoleCreate) => post<Role>('/admin/roles', body)
export const updateRole = (id: string, body: RoleUpdate) => put<Role>(`/admin/roles/${id}`, body)
export const deleteRole = (id: string) => del<void>(`/admin/roles/${id}`)
export const setRolePermissions = (id: string, permissions: string[]) =>
  put<Role>(`/admin/roles/${id}/permissions`, { permissions })
export const bulkAssignRole = (id: string, body: RoleBulkAssign) =>
  post<RoleBulkResult>(`/admin/roles/${id}/bulk`, body)

// ---- audit ------------------------------------------------------------------

export const listAuditLogs = (params: AuditQuery) =>
  get<Page<AuditLog>>('/admin/audit-logs', { params })
