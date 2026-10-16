import { describe, expect, it } from 'vitest'
import { parseMarkdownTable, splitAnswerBlocks, tableToBarOption } from '../answerBlocks'

describe('parseMarkdownTable', () => {
  it('parses headers and rows', () => {
    const parsed = parseMarkdownTable(`| 车间 | 产量 |
| --- | ---: |
| A | 10 |
| B | 20 |`)
    expect(parsed).toEqual({
      headers: ['车间', '产量'],
      rows: [
        ['A', '10'],
        ['B', '20'],
      ],
    })
  })

  it('rejects non-tables', () => {
    expect(parseMarkdownTable('| only one line |')).toBeNull()
  })
})

describe('splitAnswerBlocks', () => {
  it('extracts tables from surrounding markdown', () => {
    const blocks = splitAnswerBlocks(`说明如下：

| 项 | 值 |
| --- | --- |
| a | 1 |

结束。`)
    expect(blocks.map((b) => b.type)).toEqual(['markdown', 'table', 'markdown'])
    expect(blocks[1]).toMatchObject({ type: 'table', headers: ['项', '值'] })
  })

  it('parses echarts and mermaid fences', () => {
    const blocks = splitAnswerBlocks(`\`\`\`echarts
{"title":{"text":"产量"},"series":[{"type":"bar","data":[1,2]}]}
\`\`\`

\`\`\`mermaid
flowchart LR
  A --> B
\`\`\``)
    const types = blocks.map((b) => b.type)
    expect(types).toContain('echarts')
    expect(types).toContain('mermaid')
    expect(blocks.find((b) => b.type === 'mermaid')).toMatchObject({
      source: 'flowchart LR\n  A --> B',
    })
  })

  it('keeps incomplete fences as markdown while streaming', () => {
    const blocks = splitAnswerBlocks('前文\n```echarts\n{"a":')
    expect(blocks.every((b) => b.type === 'markdown')).toBe(true)
    expect(blocks.map((b) => (b.type === 'markdown' ? b.text : '')).join('')).toBe(
      '前文\n```echarts\n{"a":',
    )
  })

  it('rejects echarts payloads with functions', () => {
    const blocks = splitAnswerBlocks('```echarts\n{"formatter":"function(){}"}\n```')
    expect(blocks[0]?.type).toBe('markdown')
  })
})

describe('tableToBarOption', () => {
  it('builds bar series from numeric columns', () => {
    const option = tableToBarOption(
      ['车间', '产量', '合格率'],
      [
        ['A', '10', '0.9'],
        ['B', '20', '0.8'],
      ],
    )
    expect(option).not.toBeNull()
    expect(option!.xAxis).toMatchObject({ data: ['A', 'B'] })
    expect(option!.series).toHaveLength(2)
  })

  it('returns null when there is no numeric column', () => {
    expect(
      tableToBarOption(
        ['名称', '说明'],
        [
          ['A', 'foo'],
          ['B', 'bar'],
        ],
      ),
    ).toBeNull()
  })
})
