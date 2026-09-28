// Token 预算上下文：简易估算（中文 1 字≈2 token，英文 1 词≈1 token），
// 从最新消息往前累加，超预算即停，丢弃更早消息。
export type RoleMessage = { role: string; content: string }

export const CONTEXT_TOKEN_BUDGET = 2000

const CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\uff00-\uffef]/g

export function estimateTokens(text: string): number {
  const s = text || ''
  const cjk = (s.match(CJK_RE) || []).length
  const withoutCjk = s.replace(CJK_RE, ' ')
  const words = withoutCjk.split(/[\s,，、；;|/\\？?！!：:。."'"“”‘’（）()[\]{}<>~`@#$%^&*+=_-]+/).filter(Boolean)
  let en = 0
  for (const w of words) {
    if (/[A-Za-z0-9]/.test(w)) en += 1
    else if (w.length > 0) en += Math.ceil(w.length / 4)
  }
  return cjk * 2 + en
}

export function selectByTokenBudget<T extends RoleMessage>(
  messages: T[],
  budget = CONTEXT_TOKEN_BUDGET,
): { kept: T[]; dropped: number; usedTokens: number } {
  const kept: T[] = []
  let used = 0
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] as T
    const content = (m as RoleMessage).content || ''
    const cost = estimateTokens(content) + 4
    if (kept.length > 0 && used + cost > budget) break
    // 单条超预算：截断其头部，只保留尾部能装下的部分
    if (kept.length === 0 && cost > budget) {
      let lo = 0
      let hi = content.length
      while (lo < hi) {
        const mid = Math.floor((lo + hi) / 2)
        if (estimateTokens(content.slice(mid)) + 4 <= budget) hi = mid
        else lo = mid + 1
      }
      kept.unshift({ ...(m as object), content: content.slice(lo) } as T)
      used = estimateTokens(content.slice(lo)) + 4
      break
    }
    kept.unshift(m as T)
    used += cost
  }
  return { kept, dropped: messages.length - kept.length, usedTokens: used }
}
