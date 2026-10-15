import { describe, expect, it, vi } from 'vitest'
import { dispatchChatEvent } from '@/api/chat'
import { SseParser } from '../sse'

describe('SseParser', () => {
  it('parses events split across arbitrary chunks', () => {
    const parser = new SseParser()
    const stream = 'event: meta\ndata: {"a":1}\n\nevent: token\ndata: {"text":"你好"}\n\n'
    const events = []
    for (let i = 0; i < stream.length; i += 5) events.push(...parser.push(stream.slice(i, i + 5)))
    expect(events).toEqual([
      { event: 'meta', data: '{"a":1}' },
      { event: 'token', data: '{"text":"你好"}' },
    ])
  })

  it('handles CRLF, comments, multi-line data and a missing trailing blank line', () => {
    const parser = new SseParser()
    expect(parser.push(': ping\r\n\r\nevent: x\r')).toEqual([])
    expect(parser.push('\ndata: a\r\ndata: b\r\n\r\ndata: tail')).toEqual([
      { event: 'x', data: 'a\nb' },
    ])
    expect(parser.flush()).toEqual([{ event: 'message', data: 'tail' }])
  })
})

describe('dispatchChatEvent', () => {
  it('routes chat events to handlers and ignores malformed data', () => {
    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const handlers = { onToken, onDone, onError }
    dispatchChatEvent({ event: 'token', data: '{"text":"a"}' }, handlers)
    dispatchChatEvent({ event: 'token', data: 'not json' }, handlers)
    dispatchChatEvent({ event: 'done', data: '{"grounding":"grounded"}' }, handlers)
    dispatchChatEvent({ event: 'error', data: '{"code":"LLM_UNAVAILABLE"}' }, handlers)
    expect(onToken).toHaveBeenCalledExactlyOnceWith('a')
    expect(onDone).toHaveBeenCalledWith({ grounding: 'grounded' })
    expect(onError).toHaveBeenCalledWith({ code: 'LLM_UNAVAILABLE' })
  })
})
