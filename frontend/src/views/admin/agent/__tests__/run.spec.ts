import { describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import { applyEvent, issueText, newTurn, stepText } from '../run'

describe('admin assistant run reducer', () => {
  it('folds a full run + execution into one turn', () => {
    const turn = newTurn()
    const events: [string, Record<string, unknown>][] = [
      ['run', { run_id: 'r1' }],
      ['stage', { stage: 'understand', status: 'running', detail: {} }],
      ['thought', { stage: 'understand', text: 'create a group' }],
      [
        'stage',
        { stage: 'understand', status: 'done', duration_ms: 12, detail: { intent: 'change' } },
      ],
      [
        'plan',
        {
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
      ],
      ['report', { outcome: 'awaiting_approval' }],
      ['step', { index: 0, status: 'running' }],
      ['verify', { index: 0, ok: true, code: 'group_created', params: { group: 'G' } }],
      ['step', { index: 0, status: 'done', duration_ms: 5 }],
      ['report', { outcome: 'done' }],
    ]
    for (const [type, data] of events) applyEvent(turn, type, data)

    expect(turn.runId).toBe('r1')
    expect(turn.stages).toEqual([
      { stage: 'understand', status: 'done', durationMs: 12, detail: { intent: 'change' } },
    ])
    expect(turn.thoughts).toEqual(['create a group'])
    expect(turn.steps[0]).toMatchObject({ status: 'done', durationMs: 5, check: { ok: true } })
    expect(turn.outcome).toBe('done')
  })

  it('localizes steps and issues in both languages', () => {
    i18n.global.locale.value = 'en'
    expect(stepText('create_group', { group: 'G' })).toBe('Create user group "G"')
    expect(
      issueText({
        reason: 'missing_slot',
        params: { task: 'onboard_user', fields: 'username,display_name' },
      }),
    ).toBe('"create account" still needs: username, name')
    i18n.global.locale.value = 'zh-CN'
    expect(issueText({ reason: 'user_not_found', params: { mention: 'xx' } })).toBe(
      '找不到用户「xx」',
    )
  })
})
