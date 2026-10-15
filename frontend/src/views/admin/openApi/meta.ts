import type { ApiPrincipalType, ApiScope } from '@/api/types'

export const SCOPE_INFO: Record<ApiScope, { label: string; desc: string }> = {
  retrieve: { label: '检索', desc: 'POST /open/retrieve，返回授权范围内的知识片段' },
  chat: { label: '问答', desc: 'POST /open/chat，基于授权知识生成带引用的回答（支持流式）' },
  mcp: { label: 'MCP', desc: 'POST /open/mcp，供支持 MCP 的 Agent 以工具方式调用' },
}

export const PRINCIPAL_LABEL: Record<ApiPrincipalType, string> = {
  dept: '部门',
  group: '用户组',
  role: '角色',
}

export function openApiBase(): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
  return new URL(`${base}/open`, window.location.origin).toString()
}
