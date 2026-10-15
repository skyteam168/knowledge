export interface SseEvent {
  event: string
  data: string
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const i = line.indexOf(':')
    const field = i < 0 ? line : line.slice(0, i)
    let value = i < 0 ? '' : line.slice(i + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  return data.length ? { event, data: data.join('\n') } : null
}

/** Incremental text/event-stream parser: feed decoded chunks, get complete events. */
export class SseParser {
  private buffer = ''

  push(chunk: string): SseEvent[] {
    this.buffer += chunk
    // Normalise line endings only once a block is complete, so a "\r" split from its "\n"
    // across chunks is not mistaken for a line break of its own.
    const events: SseEvent[] = []
    for (;;) {
      const text = this.buffer.replace(/\r\n|\r(?!$)/g, '\n')
      const end = text.indexOf('\n\n')
      if (end < 0) {
        this.buffer = text
        return events
      }
      const event = parseBlock(text.slice(0, end))
      if (event) events.push(event)
      this.buffer = text.slice(end + 2)
    }
  }

  /** Remaining event when the stream ends without a trailing blank line. */
  flush(): SseEvent[] {
    const rest = this.buffer.replace(/\r\n?/g, '\n')
    this.buffer = ''
    const event = parseBlock(rest)
    return event ? [event] : []
  }
}
