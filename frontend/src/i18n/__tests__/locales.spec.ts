import { describe, expect, it } from 'vitest'
import { baseCompile } from '@intlify/message-compiler'
import { localeModules, type LocaleMessages } from '../index'

function flatten(messages: LocaleMessages, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(messages)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out[path] = value
    else Object.assign(out, flatten(value, path))
  }
  return out
}

const modules = localeModules()

describe('locale modules', () => {
  it.each(Object.keys(modules))('%s: zh-CN and en have the same keys', (ns) => {
    const zh = Object.keys(flatten(modules[ns]['zh-CN'])).sort()
    const en = Object.keys(flatten(modules[ns].en)).sort()
    expect(en).toEqual(zh)
  })

  it.each(Object.keys(modules))('%s: every message compiles and is non-empty', (ns) => {
    for (const locale of ['zh-CN', 'en'] as const) {
      for (const [key, message] of Object.entries(flatten(modules[ns][locale]))) {
        const errors: string[] = []
        baseCompile(message, { onError: (e) => errors.push(e.message) })
        expect(errors, `${locale} ${ns}.${key}: ${message}`).toEqual([])
        expect(message.trim(), `${locale} ${ns}.${key}`).not.toBe('')
      }
    }
  })
})
