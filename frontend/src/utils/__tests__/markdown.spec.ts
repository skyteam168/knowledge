import { describe, expect, it } from 'vitest'
import { citationOf, codeOfCopyButton, renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('renders citation markers as clickable superscripts', () => {
    const html = renderMarkdown('年假为 5 天。[1][2]')
    expect(html).toContain('<sup class="cite" data-n="1" role="button" tabindex="0">[1]</sup>')
    expect(html).toContain('data-n="2"')
  })

  it('keeps unknown citation numbers as plain text', () => {
    const html = renderMarkdown('甲。[1] 乙。[7]', { citations: new Set([1]) })
    expect(html).toContain('data-n="1"')
    expect(html).not.toContain('data-n="7"')
    expect(html).toContain('[7]')
  })

  it('does not treat links or code as citations', () => {
    const html = renderMarkdown('[1](https://example.com) `a[2]`')
    expect(html).not.toContain('class="cite"')
    expect(html).toContain('target="_blank"')
  })

  it('escapes raw html from the model', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })
})

describe('code blocks', () => {
  it('wraps fences with a language label and copy button, escaping the code', () => {
    const html = renderMarkdown('```html" onclick="x\n<script>alert(1)</script>\n```')
    expect(html).toContain('class="code-copy"')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('onclick="x')
    expect(html).toContain('&lt;script&gt;')
  })

  it('finds the code of a clicked copy button', () => {
    const root = document.createElement('div')
    root.innerHTML = renderMarkdown('```sh\necho [1]\n```')
    const button = root.querySelector('.code-copy')
    expect(codeOfCopyButton(button)).toEqual({ code: 'echo [1]\n', el: button })
    expect(codeOfCopyButton(root)).toBeNull()
  })
})

describe('citationOf', () => {
  it('finds the citation of an event target', () => {
    const root = document.createElement('div')
    root.innerHTML = renderMarkdown('结论。[3]')
    const sup = root.querySelector('sup')
    expect(citationOf(sup)).toEqual({ n: 3, el: sup })
    expect(citationOf(root)).toBeNull()
    expect(citationOf(null)).toBeNull()
  })
})
