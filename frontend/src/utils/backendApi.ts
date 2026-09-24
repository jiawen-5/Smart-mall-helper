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
  opts: { platform?: string; onDelta: (chunk: string) => void; onSkill?: (skill: string | null) => void }
): Promise<{ skill: string | null; answer: string; data: unknown }> => {
  const resp = await fetch('/api/agent/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, platform: opts.platform || undefined }),
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

/** Skill 2：文案创意生成（多版本 + 极限词校验） */
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
