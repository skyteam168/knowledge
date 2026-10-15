export type DiffOp = 'equal' | 'add' | 'remove'

export interface DiffLine {
  op: DiffOp
  text: string
}

/** Above this many cells the LCS table is skipped and the texts are shown as replaced. */
const MAX_CELLS = 4_000_000

/** Line-level diff (longest common subsequence) between two texts. */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before ? before.split('\n') : []
  const b = after ? after.split('\n') : []
  const n = a.length
  const m = b.length
  if (n * m > MAX_CELLS) {
    return [
      ...a.map((text) => ({ op: 'remove' as const, text })),
      ...b.map((text) => ({ op: 'add' as const, text })),
    ]
  }
  // lcs[i][j] = LCS length of a[i:] and b[j:]
  const lcs: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ op: 'equal', text: a[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ op: 'remove', text: a[i++] })
    } else {
      out.push({ op: 'add', text: b[j++] })
    }
  }
  while (i < n) out.push({ op: 'remove', text: a[i++] })
  while (j < m) out.push({ op: 'add', text: b[j++] })
  return out
}

export function hasChanges(lines: DiffLine[]): boolean {
  return lines.some((l) => l.op !== 'equal')
}
