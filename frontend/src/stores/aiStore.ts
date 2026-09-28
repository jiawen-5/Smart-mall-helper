import { defineStore } from 'pinia'
import { toRaw } from 'vue'
import {
  aiDb,
  DEFAULT_USER_CONFIG,
  LEGACY_STORAGE_KEY,
  type AIHistoryItem,
  type AIUserConfig,
  type ChatMessageItem,
} from './aiDb'
import { canTransit, type ChatStatus } from '@/utils/chatStatus'

type AIStoreState = {
  history: AIHistoryItem[]
  userConfig: AIUserConfig
  chatMessages: ChatMessageItem[]
  hydrated: boolean
  loading: boolean
  chatStatus: ChatStatus
  /** 游标分页：已加载中最早一条的 createdAt；null 表示还没有可用的游标 */
  chatCursor: number | null
  /** 是否还有更早的历史可加载 */
  chatHasMore: boolean
  /** 顶部加载更多进行中 */
  chatLoadingMore: boolean
}

const MAX_HISTORY = 30
/** 单页大小：按时间倒序每次只查 20 条 */
export const CHAT_PAGE_SIZE = 20
/** 内存中最多保留的消息数（分页加载的上界，防止无限增长） */
const MAX_CHAT_MESSAGES = 200

export const useAIStore = defineStore('ai', {
  state: (): AIStoreState => ({
    history: [],
    userConfig: DEFAULT_USER_CONFIG,
    chatMessages: [],
    hydrated: false,
    loading: false,
    chatStatus: 'idle',
    chatCursor: null,
    chatHasMore: true,
    chatLoadingMore: false,
  }),
  getters: {
    recentHistory: (state) => state.history.slice(0, 10),
  },
  actions: {
    setChatStatus(next: ChatStatus) {
      if (!canTransit(this.chatStatus, next)) return
      this.chatStatus = next
    },
    forceChatStatus(next: ChatStatus) {
      this.chatStatus = next
    },
    async ensureHydrated() {
      if (this.hydrated || this.loading) return
      this.loading = true
      try {
        await migrateLegacyStorageIfNeeded()

        const [history, latestChats, totalChats, configRecord] = await Promise.all([
          aiDb.histories.orderBy('createdAt').reverse().toArray(),
          // 首屏只查最近 20 条（倒序游标分页第一页）
          aiDb.chatMessages.orderBy('createdAt').reverse().limit(CHAT_PAGE_SIZE).toArray(),
          aiDb.chatMessages.count(),
          aiDb.settings.get('userConfig'),
        ])

        this.history = history.slice(0, MAX_HISTORY)
        // reverse() 拿回来是倒序，转回正序用于渲染
        this.chatMessages = latestChats.reverse()
        this.chatCursor = this.chatMessages.length > 0 ? this.chatMessages[0]!.createdAt : null
        this.chatHasMore = totalChats > this.chatMessages.length
        this.userConfig = configRecord?.value ?? DEFAULT_USER_CONFIG
        this.hydrated = true
      } finally {
        this.loading = false
      }
    },
    /** 滚动到顶部时调用：用游标继续向前读下一页（20 条），返回新增条数 */
    async loadOlderChatMessages() {
      if (!this.hydrated || this.chatLoadingMore || !this.chatHasMore || this.chatCursor == null) return 0
      this.chatLoadingMore = true
      try {
        const total = await aiDb.chatMessages.count()
        // 同毫秒 createdAt 可能重复，游标处多取 1 条做去重
        const rows = await aiDb.chatMessages
          .where('createdAt')
          .below(this.chatCursor)
          .reverse()
          .limit(CHAT_PAGE_SIZE + 1)
          .toArray()
        const existed = new Set(this.chatMessages.map((m) => m.id))
        const fresh = rows.reverse().filter((m) => !existed.has(m.id))
        if (fresh.length > 0) {
          this.chatMessages = [...fresh, ...this.chatMessages].slice(-MAX_CHAT_MESSAGES)
          this.chatCursor = this.chatMessages[0]!.createdAt
        }
        this.chatHasMore = total > this.chatMessages.length && rows.length > CHAT_PAGE_SIZE - 1 && fresh.length > 0
        // 边界：如果库里总数已全量加载，直接关门
        if (total <= this.chatMessages.length) this.chatHasMore = false
        return fresh.length
      } finally {
        this.chatLoadingMore = false
      }
    },
    async addHistory(partial: Omit<AIHistoryItem, 'id' | 'createdAt'>) {
      const item: AIHistoryItem = {
        id: createRecordId(),
        createdAt: Date.now(),
        ...partial,
      }
      this.history.unshift(item)
      this.history = this.history.slice(0, MAX_HISTORY)
      await aiDb.histories.put(toRaw(item))
    },
    async clearHistory() {
      this.history = []
      await aiDb.histories.clear()
    },
    async addChatMessage(partial: Omit<ChatMessageItem, 'id' | 'createdAt'>) {
      const item: ChatMessageItem = {
        id: createRecordId(),
        createdAt: Date.now(),
        ...partial,
      }
      this.chatMessages.push(item)
      this.chatMessages = this.chatMessages.slice(-MAX_CHAT_MESSAGES)
      await aiDb.chatMessages.put(toRaw(item))
      return item.id
    },
    async clearChat() {
      this.chatMessages = []
      this.chatCursor = null
      this.chatHasMore = false
      await aiDb.chatMessages.clear()
    },
    // 流式高频更新：只改内存，不写 IndexedDB，结束时再 persistChatMessage 一次落盘
    patchChatMessageContent(id: string, content: string) {
      const index = this.chatMessages.findIndex((m) => m.id === id)
      if (index === -1) return
      const current = this.chatMessages[index] as ChatMessageItem
      this.chatMessages[index] = { ...current, content }
    },
    async persistChatMessage(id: string) {
      const found = this.chatMessages.find((m) => m.id === id)
      if (found) await aiDb.chatMessages.put(toRaw(found))
    },
    async updateChatMessage(id: string, patch: Partial<Pick<ChatMessageItem, 'role' | 'content'>>) {
      const index = this.chatMessages.findIndex((m) => m.id === id)
      if (index === -1) return
      const current = this.chatMessages[index] as ChatMessageItem
      const next: ChatMessageItem = {
        id: current.id,
        createdAt: current.createdAt,
        role: patch.role ?? current.role,
        content: patch.content ?? current.content,
      }
      this.chatMessages[index] = next
      await aiDb.chatMessages.put(toRaw(next))
    },
    async updateUserConfig(config: Partial<AIUserConfig>) {
      this.userConfig = { ...this.userConfig, ...config }
      await aiDb.settings.put({
        key: 'userConfig',
        value: { ...toRaw(this.userConfig) },
        updatedAt: Date.now(),
      })
    },
    async persist() {
      await Promise.all([
        syncHistories(this.history),
        syncChatMessages(this.chatMessages),
        aiDb.settings.put({
          key: 'userConfig',
          value: { ...toRaw(this.userConfig) },
          updatedAt: Date.now(),
        }),
      ])
    },
  },
})

async function syncHistories(items: AIHistoryItem[]) {
  await aiDb.histories.clear()
  const trimmed = items.slice(0, MAX_HISTORY).map((item) => toRaw(item))
  if (trimmed.length > 0) {
    await aiDb.histories.bulkPut(trimmed)
  }
}

async function syncChatMessages(items: ChatMessageItem[]) {
  await aiDb.chatMessages.clear()
  const trimmed = items.slice(-MAX_CHAT_MESSAGES).map((item) => toRaw(item))
  if (trimmed.length > 0) {
    await aiDb.chatMessages.bulkPut(trimmed)
  }
}

async function migrateLegacyStorageIfNeeded() {
  if (typeof window === 'undefined') return

  const raw = window.localStorage.getItem(LEGACY_STORAGE_KEY)
  if (!raw) return

  try {
    const parsed = JSON.parse(raw) as {
      history?: AIHistoryItem[]
      userConfig?: Partial<AIUserConfig>
      chatMessages?: ChatMessageItem[]
    }

    const [existingHistoryCount, existingChatCount, existingConfig] = await Promise.all([
      aiDb.histories.count(),
      aiDb.chatMessages.count(),
      aiDb.settings.get('userConfig'),
    ])

    if (existingHistoryCount === 0 && Array.isArray(parsed.history) && parsed.history.length > 0) {
      await aiDb.histories.bulkPut(parsed.history.slice(0, MAX_HISTORY))
    }

    if (existingChatCount === 0 && Array.isArray(parsed.chatMessages) && parsed.chatMessages.length > 0) {
      await aiDb.chatMessages.bulkPut(parsed.chatMessages.slice(-MAX_CHAT_MESSAGES))
    }

    if (!existingConfig) {
      await aiDb.settings.put({
        key: 'userConfig',
        value: { ...DEFAULT_USER_CONFIG, ...(parsed.userConfig || {}) },
        updatedAt: Date.now(),
      })
    }

    window.localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch (error) {
    console.error('迁移旧版 AI 存储失败:', error)
  }
}

function createRecordId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}
