import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import ini from 'highlight.js/lib/languages/ini'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import shell from 'highlight.js/lib/languages/shell'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

const LANGUAGES = {
  bash,
  css,
  go,
  ini,
  java,
  javascript,
  json,
  markdown,
  python,
  shell,
  sql,
  typescript,
  xml,
  yaml,
}
for (const [name, lang] of Object.entries(LANGUAGES)) hljs.registerLanguage(name, lang)
hljs.registerAliases(['vue', 'html'], { languageName: 'xml' })
hljs.registerAliases(['dockerfile', 'env', 'toml'], { languageName: 'ini' })

/** Detection is skipped above this size; long blocks stay plain. */
const MAX_AUTO_CHARS = 20000

/** Highlighted HTML (spans with hljs-* classes, content escaped), or null to render plain. */
export function highlightCode(code: string, lang: string): string | null {
  const name = lang.toLowerCase()
  try {
    if (name && hljs.getLanguage(name)) {
      return hljs.highlight(code, { language: name, ignoreIllegals: true }).value
    }
    if ((!name || name === 'text') && code.length <= MAX_AUTO_CHARS) {
      const auto = hljs.highlightAuto(code)
      return auto.relevance >= 5 ? auto.value : null
    }
  } catch {
    return null
  }
  return null
}
