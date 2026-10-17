import MarkdownIt, { type StateInline } from 'markdown-it'

export interface RenderEnv {
  /** Citation numbers that exist; others render as plain text. Omit to accept all. */
  citations?: ReadonlySet<number>
}

const CITE = /^\[(\d{1,3})\](?!\()/
const IMAGE_REF_PREFIX = 'ekb-image:'

function citationRule(state: StateInline, silent: boolean): boolean {
  if (state.src.charCodeAt(state.pos) !== 0x5b /* [ */) return false
  const match = CITE.exec(state.src.slice(state.pos))
  if (!match) return false
  const n = Number(match[1])
  const known = (state.env as RenderEnv).citations
  if (known && !known.has(n)) return false
  if (!silent) {
    const token = state.push('citation', 'sup', 0)
    token.meta = { n }
  }
  state.pos += match[0].length
  return true
}

function create(): MarkdownIt {
  // html: false — answers are model output and must never inject markup.
  const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
  md.inline.ruler.before('link', 'citation', citationRule)
  md.renderer.rules.citation = (tokens, idx) => {
    const n = (tokens[idx].meta as { n: number }).n
    return `<sup class="cite" data-n="${n}" role="button" tabindex="0">[${n}]</sup>`
  }
  const defaultLink =
    md.renderer.rules.link_open ??
    ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    tokens[idx].attrSet('target', '_blank')
    tokens[idx].attrSet('rel', 'noopener noreferrer')
    return defaultLink(tokens, idx, options, env, self)
  }
  md.renderer.rules.fence = (tokens, idx) => {
    const token = tokens[idx]
    const lang = md.utils.escapeHtml(token.info.trim().split(/\s+/)[0] || 'text')
    return (
      `<div class="code-block"><div class="code-head"><span class="code-lang">${lang}</span>` +
      `<button type="button" class="code-copy">复制</button></div>` +
      `<pre><code>${md.utils.escapeHtml(token.content)}</code></pre></div>`
    )
  }
  // Safe images only: https or same-origin /api| /oidc paths (presigned previews).
  md.renderer.rules.image = (tokens, idx) => {
    const token = tokens[idx]
    const src = token.attrGet('src') || ''
    const alt = md.utils.escapeHtml(token.content || '')
    // Placeholder while streaming; the final answer carries the presigned URL.
    if (src.startsWith(IMAGE_REF_PREFIX)) {
      return `<span class="md-img-pending">${alt || '图片'}</span>`
    }
    if (!isSafeImageSrc(src)) {
      return `<span class="md-img-blocked" title="不安全的图片地址">${alt || '图片'}</span>`
    }
    const safe = md.utils.escapeHtml(src)
    return (
      `<span class="md-img-wrap">` +
      `<img class="md-img" src="${safe}" alt="${alt}" loading="lazy" role="button" tabindex="0" data-src="${safe}" />` +
      `</span>`
    )
  }
  return md
}

export function isSafeImageSrc(src: string): boolean {
  const s = src.trim()
  if (!s || s.startsWith('data:') || s.startsWith('javascript:')) return false
  if (s.startsWith('https://')) return true
  if (s.startsWith('/api/') || s.startsWith('/oidc/')) return true
  return false
}

/** Code text of a clicked copy button inside rendered markdown, if any. */
export function codeOfCopyButton(
  target: EventTarget | null,
): { code: string; el: HTMLElement } | null {
  if (!(target instanceof HTMLElement)) return null
  const el = target.closest<HTMLElement>('.code-copy')
  const code = el?.closest('.code-block')?.querySelector('code')?.textContent
  return el && code != null ? { code, el } : null
}

const md = create()

export function renderMarkdown(source: string, env: RenderEnv = {}): string {
  return md.render(source, { ...env })
}

/** Citation number of a clicked/hovered element inside rendered markdown, if any. */
export function citationOf(target: EventTarget | null): { n: number; el: HTMLElement } | null {
  if (!(target instanceof HTMLElement)) return null
  const el = target.closest<HTMLElement>('sup.cite')
  const n = Number(el?.dataset.n)
  return el && Number.isInteger(n) ? { n, el } : null
}
