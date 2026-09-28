import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

// 流式半截 Markdown 自动补全：未闭合代码块补 ```，未闭合行内 code/加粗补后缀，表格缺尾管补 |
export function completeStreamMarkdown(src: string): string {
  let out = src
  const fences = (out.match(/```/g) || []).length
  if (fences % 2 === 1) out += '\n```'
  const inlineCodes = (out.match(/`/g) || []).length
  // fences 已处理偶数个 ```，奇数个单反引号再补一个
  if (inlineCodes % 2 === 1 && fences % 2 === 0) out += '`'
  const bold = (out.match(/\*\*/g) || []).length
  if (bold % 2 === 1) out += '**'
  const lines = out.split('\n')
  const last = lines[lines.length - 1]
  if (last && last.includes('|') && !last.trimEnd().endsWith('|') && last.split('|').length >= 3) {
    lines[lines.length - 1] = `${last} |`
    out = lines.join('\n')
  }
  return out
}

// markdown-it 渲染 + DOMPurify 白名单消毒（等价 rehype-sanitize，防御 AI 输出 XSS）
// html:false 已禁用原始 HTML，这里再做一次纵深消毒。
export function renderSafeMarkdown(src: string): string {
  const completed = completeStreamMarkdown(src || '')
  const raw = md.render(completed)
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'code', 'pre', 'ul', 'ol', 'li', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'h1', 'h2', 'h3', 'h4', 'hr', 'del'],
    ALLOWED_ATTR: ['href', 'title', 'target', 'rel'],
  })
}

// 滚动锚定：只有用户贴底（距底 < 48px）时才自动跟随，防止阅读历史时被拽到底部
export function isNearBottom(el: HTMLElement, threshold = 48): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < threshold
}
