import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 15000 })

export type Metrics = { today_sales: number; today_orders: number; active_users: number; conversion_rate: number }
export type Trend = { dates: string[]; sales: number[]; orders: number[] }

export const fetchMetrics = (platform?: string) =>
  api.get<Metrics>('/dashboard/metrics', { params: { platform: platform || undefined } }).then((r) => r.data)

export const fetchTrend = (range = '7d', platform?: string) =>
  api.get<Trend>('/dashboard/trend', { params: { range, platform: platform || undefined } }).then((r) => r.data)

export const fetchFunnel = (platform?: string) =>
  api.get<{ behavior_type: string; count: number }[]>('/dashboard/funnel', { params: { platform: platform || undefined } }).then((r) => r.data)

export type ProductItem = {
  global_product_id: string
  product_name: string
  category: string | null
  subcategory: string | null
  platform: string | null
  price: number
  brand: string | null
  stock_status: string | null
  tags: string | null
  sales: number
  revenue: number
}

export const fetchProducts = (params: { keyword?: string; category?: string; platform?: string; page?: number; page_size?: number }) =>
  api.get<{ total: number; items: ProductItem[] }>('/products', { params }).then((r) => r.data)

export const fetchCategories = () =>
  api.get<{ category: string; count: number }[]>('/products/categories').then((r) => r.data)

export type Segments = { levels: { user_level: string; count: number }[]; frequency: Record<string, number> }

export const fetchSegments = (platform?: string) =>
  api.get<Segments>('/users/segments', { params: { platform: platform || undefined } }).then((r) => r.data)

export const fetchOrders = (params: { status?: string; platform?: string; page?: number; page_size?: number }) =>
  api.get('/orders', { params }).then((r) => r.data)

export const fetchOrderHealth = (platform?: string, days = 30) =>
  api.get<{ status: string; count: number; pct: number }[]>('/orders/health', { params: { platform: platform || undefined, days } }).then((r) => r.data)

export const fetchPlatforms = () => api.get('/meta/platforms').then((r) => r.data as { code: string; name: string }[])

/** Skill 1：商品与核心指标查询（数值由后端代码计算，LLM 只做语言整理） */
export const askAgentSkill = (question: string, platform?: string) =>
  api.post('/agent/ask', { question, platform: platform || undefined }).then((r) => r.data as { skill: string | null; answer: string; data: unknown })

/** Skill 流式调用：走 /agent/ask/stream（SSE），文案/客服/查数统一逐字输出 */
export const askAgentSkillStream = async (
  question: string,
  opts: { platform?: string; history?: { role: string; content: string }[]; budget?: number; onDelta: (chunk: string) => void; onSkill?: (skill: string | null) => void }
): Promise<{ skill: string | null; answer: string; data: unknown }> => {
  const orderMatch = question.match(/(?:订单号|订单|order[_ ]?id)\s*[:：]?\s*([A-Za-z0-9\-_]{6,40})/i)
  // skill 上下文同样走 token 预算：从最新往前累加，超预算丢弃更早消息
  const budget = opts.budget ?? 2000
  const { selectByTokenBudget: _select } = await import('./contextBudget')
  const history = _select(
    (opts.history || [])
      .map((m) => ({ role: m.role, content: (m.content || '').trim() }))
      .filter((m) => m.content.length > 0),
    budget,
  ).kept
  const resp = await fetch('/api/agent/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      platform: opts.platform || undefined,
      history,
      order_id: orderMatch ? orderMatch[1] : undefined,
    }),
  })
  if (!resp.ok || !resp.body) throw new Error(`Skill 流式请求失败：${resp.status}`)
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let skill: string | null = null
  let answer = ''
  let data: unknown = null
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() || ''
    for (const f of frames) {
      const line = f.trim()
      if (!line.startsWith('data:')) continue
      try {
        const payload = JSON.parse(line.slice(5).trim())
        if (typeof payload.skill !== 'undefined' && payload.delta === undefined && !payload.done) skill = payload.skill
        if (typeof payload.delta === 'string') {
          answer += payload.delta
          opts.onDelta(payload.delta)
        }
        if (payload.done) {
          skill = payload.skill ?? skill
          data = payload.data ?? null
        }
      } catch { /* 忽略半包解析失败 */ }
    }
  }
  opts.onSkill?.(skill)
  return { skill, answer, data }
}

const SKILL_HINT_RE = /(销量|销售额|销售总额|总额|gmv|营业额|转化率|环比|同比|卖了多少|卖得|滞销|热销|爆款|总销售额|总订单|订单数|成交额|今天.*(销|订单|额)|昨天.*(销|订单|额)|对比.*(商品|款|SKU)|查.*(商品|销量|库存|价格)|文案|标题|卖点|口播|种草|直播话术|宣传语|标语|slogan|详情页|主图|营销|广告词|脚本|帮我写|帮我起|提炼.*卖点|换个说法|改写|客服|售后|退货|退款|换货|发货|物流|快递|缺货|补货|发票|运费|邮费|包邮|尺码|尺寸|破损|漏发|少发|错发|投诉|价保|催发货|话术)/i
export const looksLikeSkillQuery = (text: string) => SKILL_HINT_RE.test(text || '')

/** 意图路由：只返回 skill 名，不跑 Skill/LLM，前端据此决定打哪个流式接口
 *  history 先按 2000 token 预算裁剪再发送，线上传的即实际用的上下文 */
export const routeSkill = async (question: string, history?: { role: string; content: string }[]) => {
  const { selectByTokenBudget } = await import('./contextBudget')
  const trimmed = selectByTokenBudget(
    (history || []).map((m) => ({ role: m.role, content: (m.content || '').trim() })).filter((m) => m.content.length > 0),
  ).kept
  return api.post('/agent/route', { question, history: trimmed }).then((r) => r.data as { skill: string | null; question: string })
}

/** 通用 Skill 流式读取：thinking → tool_calling → answering */
const readSkillStream = async (
  url: string,
  payload: Record<string, unknown>,
  opts: { onDelta: (chunk: string) => void; onStatus?: (s: string) => void; onSkill?: (skill: string | null) => void },
): Promise<{ skill: string | null; answer: string; data: unknown }> => {
  const resp = await fetch(`/api${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!resp.ok || !resp.body) throw new Error(`Skill 流式请求失败：${resp.status}`)
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let skill: string | null = null
  let answer = ''
  let data: unknown = null
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() || ''
    for (const f of frames) {
      const line = f.trim()
      if (!line.startsWith('data:')) continue
      try {
        const p = JSON.parse(line.slice(5).trim())
        if (p.status) opts.onStatus?.(p.status)
        if (p.skill) skill = p.skill
        if (typeof p.delta === 'string') {
          answer += p.delta
          opts.onDelta(p.delta)
        }
        if (p.done) {
          skill = p.skill ?? skill
          data = p.data ?? null
        }
      } catch { /* 忽略半包 */ }
    }
  }
  opts.onSkill?.(skill)
  return { skill, answer, data }
}

/** 查数 Skill 流式（网络显示调用 product-metrics 接口）
 *  history 先按 2000 token 裁剪：线上传的就是实际用的上下文，后端会再按同口径兜底裁一次 */
export const streamProductMetrics = async (
  question: string,
  opts: { platform?: string; history?: { role: string; content: string }[]; onDelta: (c: string) => void; onStatus?: (s: string) => void },
) => {
  const { selectByTokenBudget } = await import('./contextBudget')
  const history = selectByTokenBudget(
    (opts.history || []).map((m) => ({ role: m.role, content: (m.content || '').trim() })).filter((m) => m.content.length > 0),
  ).kept
  return readSkillStream('/agent/skill/product-metrics/stream', { question, platform: opts.platform || undefined, history }, opts)
}

/** 文案 Skill 流式（网络显示调用 copywriting 接口，带裁剪后上下文，支持"再来一个"类追问） */
export const streamCopywriting = async (
  payload: { question: string; platform?: string; style?: string; variants?: number; history?: { role: string; content: string }[] },
  opts: { onDelta: (c: string) => void; onStatus?: (s: string) => void },
) => {
  const { selectByTokenBudget } = await import('./contextBudget')
  const history = selectByTokenBudget(
    (payload.history || []).map((m) => ({ role: m.role, content: (m.content || '').trim() })).filter((m) => m.content.length > 0),
  ).kept
  return readSkillStream('/agent/skill/copywriting/stream', { ...payload, history: history.length ? history : undefined }, opts)
}

/** 客服 Skill 流式（网络显示调用 customer-service 接口，带裁剪后上下文） */
export const streamCustomerService = async (
  payload: { question: string; platform?: string; order_id?: string; history?: { role: string; content: string }[] },
  opts: { onDelta: (c: string) => void; onStatus?: (s: string) => void },
) => {
  const { selectByTokenBudget } = await import('./contextBudget')
  const history = selectByTokenBudget(
    (payload.history || []).map((m) => ({ role: m.role, content: (m.content || '').trim() })).filter((m) => m.content.length > 0),
  ).kept
  return readSkillStream('/agent/skill/customer-service/stream', { ...payload, history }, opts)
}
export const skillCopywriting = (payload: {
  question?: string
  product_name?: string
  platform?: string
  style?: string
  variants?: number
  length?: number
  regenerate?: boolean
  avoid?: string[]
}) => api.post('/agent/skill/copywriting', payload).then((r) => r.data)

/** Skill 3：客服回复（FAQ 优先，未命中走 LLM） */
export const skillCustomerService = (payload: {
  question: string
  platform?: string
  order_id?: string
  product_name?: string
  history?: { role: string; content: string }[]
}) => api.post('/agent/skill/customer-service', payload).then((r) => r.data)

export const fetchFaqList = (category?: string) =>
  api.get('/agent/faq', { params: { category: category || undefined } }).then((r) => r.data)

const SKILL_ICON: Record<string, string> = {
  product_metrics: '📊',
  copywriting: '✍️',
  customer_service: '💬',
}
export const skillIcon = (skill: string | null | undefined) => SKILL_ICON[skill || ''] || '🤖'
