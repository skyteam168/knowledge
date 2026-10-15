import { computed, ref } from 'vue'
import { getDepartmentTree } from '@/api/admin'
import type { DepartmentNode } from '@/api/types'

export function flattenTree(nodes: DepartmentNode[]): DepartmentNode[] {
  return nodes.flatMap((n) => [n, ...flattenTree(n.children)])
}

export function useDepartmentTree() {
  const tree = ref<DepartmentNode[]>([])
  const loading = ref(false)
  const nameById = computed(
    () => new Map(flattenTree(tree.value).map((d) => [d.id, d.name] as const)),
  )

  async function reload(): Promise<void> {
    loading.value = true
    try {
      tree.value = await getDepartmentTree()
    } finally {
      loading.value = false
    }
  }

  function departmentName(id: string | null | undefined): string {
    return (id && nameById.value.get(id)) || '-'
  }

  return { tree, loading, reload, departmentName }
}
