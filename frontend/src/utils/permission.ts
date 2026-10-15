export type PermissionRequirement = string | readonly string[]

/** Same semantics as the backend: `*` grants all, `prefix:*` grants every `prefix:xxx`. */
export function hasPermission(granted: readonly string[], required: string): boolean {
  if (granted.includes('*') || granted.includes(required)) return true
  const prefix = required.split(':', 1)[0]
  return granted.includes(`${prefix}:*`)
}

/** True when any of the required permissions is granted (an empty requirement passes). */
export function hasAnyPermission(
  granted: readonly string[],
  required: PermissionRequirement | undefined,
): boolean {
  if (required === undefined) return true
  const list = typeof required === 'string' ? [required] : required
  return list.length === 0 || list.some((r) => hasPermission(granted, r))
}
