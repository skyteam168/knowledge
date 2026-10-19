import { beforeEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import type { AgentRunDetail } from '@/api/types'
import { newTurn } from '../run'
import { accessGraph, label, planFlowchart, replayTurn, resultTables } from '../visual'

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

describe('resultTables', () => {
  it('turns a list of records into one localized table', () => {
    const [table] = resultTables([
      { username: 'hien', display_name: 'Hien', active: true, roles: ['编辑者(editor)'] },
      { username: 'li', display_name: '李', active: false, roles: [] },
    ])
    expect(table.headers).toEqual(['账号', '姓名', '启用', '角色'])
    expect(table.rows).toEqual([
      ['hien', 'Hien', '是', '编辑者(editor)'],
      ['li', '李', '否', ''],
    ])
  })

  it('turns plain lists into a value column', () => {
    expect(resultTables(['张三 (zs)', '李四 (ls)'])).toEqual([
      { title: undefined, headers: ['值'], rows: [['张三 (zs)'], ['李四 (ls)']] },
    ])
    expect(resultTables([])).toEqual([])
  })

  it('splits an object into fields + nested record tables', () => {
    const tables = resultTables({
      knowledge_base: 'IT 知识库',
      visibility: 'restricted',
      entries: [{ type: 'dept', name: 'IT', permission: 'edit', active: true }],
    })
    expect(tables).toHaveLength(2)
    expect(tables[0].rows).toEqual([
      ['知识库', 'IT 知识库'],
      ['可见范围', '仅授权成员'],
    ])
    expect(tables[1].title).toBe('授权明细')
    expect(tables[1].rows[0]).toEqual(['部门', 'IT', '编辑', '是'])
  })

  it('formats structured permission sources inside a cell', () => {
    const [, kbs] = resultTables({
      user: 'hien',
      knowledge_bases: [
        {
          name: 'KB',
          permission: 'edit',
          via: [{ type: 'group', name: 'ERP', permission: 'edit' }],
        },
      ],
    })
    expect(kbs.rows[0][2]).toBe('用户组 · ERP · 编辑')
  })
})

describe('platform results', () => {
  it('formats nested records and timestamps in cells', () => {
    const [fields] = resultTables({
      outbox: { pending: 2, dead: 0 },
      checked_at: '2026-10-19T01:02:03+00:00',
    })
    expect(fields.rows[0]).toEqual(['同步队列', '待处理: 2 · 死信: 0'])
    expect(fields.rows[1][1]).toMatch(/^2026-10-19 \d{2}:02:03$/)
  })
})

describe('mermaid sources', () => {
  it('escapes data in labels', () => {
    expect(label('a"b<c>\nd')).toBe('"a#quot;b#lt;c#gt; d"')
  })

  it('breaks long CJK labels into short lines', () => {
    const text = `3. ${'在知识库上给用户组授予只读权限'.repeat(2)}`
    const lines = label(text).slice(1, -1).split('<br/>')
    expect(lines.length).toBe(3)
    expect(lines.join('')).toBe(text)
  })

  it('draws user → principal → knowledge base chains', () => {
    const src = accessGraph('explain_user_access', {
      user: 'Hien (hien)',
      knowledge_bases: [
        { name: 'KB1', via: [{ type: 'group', name: 'ERP', permission: 'edit' }] },
        { name: 'KB2', via: [{ type: 'group', name: 'ERP', permission: 'read' }] },
      ],
    })!
    expect(src.split('\n')[1]).toBe('graph LR')
    expect(src).toContain('U["Hien (hien)"]')
    expect(src.match(/U --> P0/g)).toHaveLength(1)
    expect(src).toContain('P0 -- "编辑" --> K0')
    expect(src).toContain('P0 -- "只读" --> K1')
    expect(accessGraph('list_roles', [])).toBeNull()
  })

  it('marks inactive grantees on knowledge base access graphs', () => {
    const src = accessGraph('get_kb_access', {
      knowledge_base: 'KB',
      visibility: 'org',
      entries: [{ type: 'user', name: 'old', permission: 'manage', active: false }],
    })!
    expect(src).toContain('ORG("组织内所有人") -- "只读" --> K')
    expect(src).toContain('class E0 inactive')
  })

  it('colors plan steps by execution status', () => {
    const turn = newTurn()
    turn.plan = {
      run_id: 'r',
      risk: 'low',
      needs_ack: false,
      expires_in: 60,
      steps: [
        {
          tool: 'create_group',
          args: {},
          display: { group: 'G' },
          warnings: [],
          risk: 'low',
          risk_reasons: [],
        },
        {
          tool: 'create_group',
          args: {},
          display: { group: 'H' },
          warnings: [],
          risk: 'low',
          risk_reasons: [],
        },
      ],
    }
    turn.steps = [{ status: 'done' }, { status: 'rolled_back' }]
    turn.outcome = 'failed'
    const src = planFlowchart(turn)
    expect(src).toContain('N0["1. 新建用户组「G」"]')
    expect(src).toContain('class N0 done')
    expect(src).toContain('class N1 failed')
    expect(src).toContain('class E failed')
  })
})

describe('replayTurn', () => {
  const base: AgentRunDetail = {
    id: 'r1',
    message: 'm',
    status: 'awaiting_approval',
    intent: 'change',
    language: 'zh',
    understand_mode: 'tools',
    risk: 'low',
    step_count: 1,
    created_at: '2026-10-17T00:00:00Z',
    executed_at: null,
    expires_at: '2026-10-17T00:30:00Z',
    events: [
      { type: 'run', data: { run_id: 'r1' } },
      {
        type: 'plan',
        data: {
          run_id: 'r1',
          risk: 'low',
          needs_ack: false,
          expires_in: 1800,
          steps: [
            {
              tool: 'create_group',
              args: {},
              display: { group: 'G' },
              warnings: [],
              risk: 'low',
              risk_reasons: [],
            },
          ],
        },
      },
      { type: 'report', data: { outcome: 'awaiting_approval' } },
    ],
    exec_events: [],
  }

  it('keeps an unexpired plan confirmable', () => {
    const turn = replayTurn(base, Date.parse('2026-10-17T00:10:00Z'))
    expect(turn.plan?.run_id).toBe('r1')
    expect(turn.outcome).toBe('awaiting_approval')
  })

  it('marks an expired plan and applies execution events', () => {
    expect(replayTurn(base, Date.parse('2026-10-17T01:00:00Z')).outcome).toBe('expired')
    const done = replayTurn({
      ...base,
      status: 'done',
      exec_events: [
        { type: 'run', data: { run_id: 'r1' } },
        { type: 'step', data: { index: 0, status: 'done' } },
        { type: 'report', data: { outcome: 'done' } },
        { type: 'done', data: {} },
      ],
    })
    expect(done.steps[0].status).toBe('done')
    expect(done.outcome).toBe('done')
  })
})
