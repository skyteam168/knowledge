/** Split assistant markdown into renderable blocks (text / table / echarts / mermaid). */

export type AnswerBlock =
  | { type: 'markdown'; text: string }
  | { type: 'table'; headers: string[]; rows: string[][]; raw: string }
  | { type: 'echarts'; option: Record<string, unknown>; raw: string }
  | { type: 'mermaid'; source: string }

const SPECIAL = new Set(['echarts', 'chart', 'mermaid'])

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-{3,}:?$/.test(c.trim()))
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((c) => c.trim())
}

/** Parse a GFM pipe table into headers + body rows (separator row dropped). */
export function parseMarkdownTable(block: string): { headers: string[]; rows: string[][] } | null {
  const lines = block
    .trim()
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.startsWith('|'))
  if (lines.length < 2) return null
  const headers = splitRow(lines[0])
  if (!headers.length || !isSeparatorRow(splitRow(lines[1]))) return null
  const rows = lines.slice(2).map(splitRow).filter((r) => r.some((c) => c.length > 0))
  return { headers, rows }
}

function sanitizeEchartsOption(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const json = JSON.stringify(value)
  if (/\bfunction\b|=>|new\s+Function|\bimport\b|\beval\b/i.test(json)) return null
  return value as Record<string, unknown>
}

function pushMarkdown(out: AnswerBlock[], text: string): void {
  if (!text) return
  const re = /(?:^|\n)((?:\|[^\n]*\|[ \t]*\r?\n)+)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const full = m[0]
    const tableText = m[1]
    const start = m.index + (full.startsWith('\n') ? 1 : 0)
    if (start > last) out.push({ type: 'markdown', text: text.slice(last, start) })
    const parsed = parseMarkdownTable(tableText)
    if (parsed) {
      out.push({
        type: 'table',
        headers: parsed.headers,
        rows: parsed.rows,
        raw: tableText.trim(),
      })
    } else {
      out.push({ type: 'markdown', text: tableText })
    }
    last = m.index + full.length
  }
  if (last < text.length) out.push({ type: 'markdown', text: text.slice(last) })
}

/**
 * Split assistant content into blocks.
 * Incomplete fences (still streaming) stay inside markdown so the cursor keeps moving.
 */
export function splitAnswerBlocks(content: string): AnswerBlock[] {
  const out: AnswerBlock[] = []
  let i = 0
  while (i < content.length) {
    const start = content.indexOf('```', i)
    if (start < 0) {
      pushMarkdown(out, content.slice(i))
      break
    }
    if (start > i) pushMarkdown(out, content.slice(i, start))
    const lineEnd = content.indexOf('\n', start)
    if (lineEnd < 0) {
      pushMarkdown(out, content.slice(start))
      break
    }
    const info = content
      .slice(start + 3, lineEnd)
      .trim()
      .split(/\s+/)[0]
      ?.toLowerCase()
    const close = content.indexOf('\n```', lineEnd)
    if (close < 0) {
      pushMarkdown(out, content.slice(start))
      break
    }
    const body = content.slice(lineEnd + 1, close)
    let end = close + 4
    while (end < content.length && content[end] !== '\n' && content[end] !== '\r') end += 1
    if (content[end] === '\r') end += 1
    if (content[end] === '\n') end += 1

    if (info && SPECIAL.has(info)) {
      if (info === 'mermaid') {
        out.push({ type: 'mermaid', source: body.replace(/\s+$/, '') })
      } else {
        try {
          const option = sanitizeEchartsOption(JSON.parse(body))
          if (option) out.push({ type: 'echarts', option, raw: body })
          else pushMarkdown(out, content.slice(start, end))
        } catch {
          pushMarkdown(out, content.slice(start, end))
        }
      }
    } else {
      pushMarkdown(out, content.slice(start, end))
    }
    i = end
  }
  return out.length ? out : [{ type: 'markdown', text: content }]
}

/** Build a simple bar option from a numeric table (first col = categories). */
export function tableToBarOption(
  headers: string[],
  rows: string[][],
): Record<string, unknown> | null {
  if (headers.length < 2 || rows.length === 0) return null
  const numericCols: number[] = []
  for (let c = 1; c < headers.length; c++) {
    const vals = rows.map((r) => r[c] ?? '')
    const nums = vals.filter((v) => v !== '' && !Number.isNaN(Number(v)))
    if (nums.length >= Math.ceil(rows.length / 2) && nums.length > 0) numericCols.push(c)
  }
  if (!numericCols.length) return null
  const categories = rows.map((r) => r[0] || '—')
  return {
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 48, right: 16, top: 40, bottom: 48, containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { rotate: categories.some((c) => c.length > 6) ? 30 : 0 },
    },
    yAxis: { type: 'value' },
    series: numericCols.map((c) => ({
      name: headers[c] || `列${c}`,
      type: 'bar',
      data: rows.map((r) => {
        const v = r[c]
        if (v === '' || v == null) return null
        const n = Number(v)
        return Number.isFinite(n) ? n : null
      }),
    })),
  }
}
