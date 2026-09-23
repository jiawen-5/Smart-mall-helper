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

const SKILL_HINT_RE = /(销量|销售额|销售总额|总额|gmv|营业额|转化率|环比|同比|卖了多少|卖得|滞销|热销|爆款|总销售额|总订单|订单数|成交额|今天.*(销|订单|额)|昨天.*(销|订单|额)|对比.*(商品|款|SKU)|查.*(商品|销量|库存|价格))/i
export const looksLikeSkillQuery = (text: string) => SKILL_HINT_RE.test(text || '')
