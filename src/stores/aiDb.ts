import Dexie, { type Table } from 'dexie'

export type AIHistoryType = 'title' | 'copy' | 'qa'

export type AIHistoryItem = {
  id: string
  type: AIHistoryType
  input: string
  output: string
  createdAt: number
}

export type ChatMessageItem = {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
}

export type AIUserConfig = {
  tone: string
  maxTokens: number
  temperature: number
}

export type AISettingsItem = {
  key: 'userConfig'
  value: AIUserConfig
  updatedAt: number
}

class AIAppDatabase extends Dexie {
  histories!: Table<AIHistoryItem, string>
  chatMessages!: Table<ChatMessageItem, string>
  settings!: Table<AISettingsItem, string>

  constructor() {
    super('smart-mall-helper-ai')

    this.version(1).stores({
      histories: 'id, type, createdAt',
      chatMessages: 'id, role, createdAt',
      settings: 'key, updatedAt',
    })
  }
}

export const aiDb = new AIAppDatabase()

export const DEFAULT_USER_CONFIG: AIUserConfig = {
  tone: '活力年轻',
  maxTokens: 500,
  temperature: 0.7,
}

export const LEGACY_STORAGE_KEY = 'smh_ai_store_v1'
