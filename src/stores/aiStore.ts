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

type AIStoreState = {
  history: AIHistoryItem[]
  userConfig: AIUserConfig
  chatMessages: ChatMessageItem[]
  hydrated: boolean
  loading: boolean
}

const MAX_HISTORY = 30
const MAX_CHAT_MESSAGES = 50

export const useAIStore = defineStore('ai', {
  state: (): AIStoreState => ({
    history: [],
    userConfig: DEFAULT_USER_CONFIG,
    chatMessages: [],
    hydrated: false,
    loading: false,
  }),
  getters: {
    recentHistory: (state) => state.history.slice(0, 10),
  },
  actions: {
    async ensureHydrated() {
      if (this.hydrated || this.loading) return
      this.loading = true
      try {
        await migrateLegacyStorageIfNeeded()

        const [history, chatMessages, configRecord] = await Promise.all([
          aiDb.histories.orderBy('createdAt').reverse().toArray(),
          aiDb.chatMessages.orderBy('createdAt').toArray(),
          aiDb.settings.get('userConfig'),
        ])

        this.history = history.slice(0, MAX_HISTORY)
        this.chatMessages = chatMessages.slice(-MAX_CHAT_MESSAGES)
        this.userConfig = configRecord?.value ?? DEFAULT_USER_CONFIG
        this.hydrated = true
      } finally {
        this.loading = false
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
      await aiDb.chatMessages.clear()
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
