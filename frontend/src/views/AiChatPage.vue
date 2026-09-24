<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close, Promotion, Setting, Delete } from '@element-plus/icons-vue'
import { buildChatContext, chatAIStream } from '@/utils/aiApi'
import { askAgentSkillStream, looksLikeSkillQuery, skillIcon } from '@/utils/backendApi'
import { useAIStore } from '@/stores/aiStore'

const router = useRouter()
const aiStore = useAIStore()

const exitChatPage = () => {
  router.push('/assistant')
}
const chatInput = ref('')
const chatSending = ref(false)
const chatListRef = ref<HTMLElement | null>(null)
const settingsVisible = ref(false)

const maxTokens = ref(aiStore.userConfig.maxTokens)
const temperature = ref(aiStore.userConfig.temperature)

const chatMessages = computed(() => aiStore.chatMessages)

const scrollToBottom = async () => {
  await nextTick()
  requestAnimationFrame(() => {
    const el = chatListRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

watch(
  () => chatMessages.value.length,
  () => void scrollToBottom()
)

onMounted(async () => {
  await aiStore.ensureHydrated().catch(() => {})
  maxTokens.value = aiStore.userConfig.maxTokens
  temperature.value = aiStore.userConfig.temperature
  void scrollToBottom()
})

const openSettings = () => {
  maxTokens.value = aiStore.userConfig.maxTokens
  temperature.value = aiStore.userConfig.temperature
  settingsVisible.value = true
}

const applySettings = async () => {
  await aiStore.updateUserConfig({ maxTokens: maxTokens.value, temperature: temperature.value })
  settingsVisible.value = false
  ElMessage.success('设置已更新')
}

const clearChat = () => {
  aiStore.clearChat()
  ElMessage.success('已清空对话历史')
}

const handleSend = async () => {
  const content = chatInput.value.trim()
  if (!content || chatSending.value) return

  chatSending.value = true
  await aiStore.addChatMessage({ role: 'user', content })
  chatInput.value = ''

  try {
    // Skill 优先：查数/文案/客服统一走后端 Skill 流式接口（/agent/ask/stream），逐字输出
    let reusedAssistantId: string | null = null
    if (looksLikeSkillQuery(content)) {
      try {
        const assistantId = await aiStore.addChatMessage({ role: 'assistant', content: '' })
        let acc = ''
        const res = await askAgentSkillStream(content, {
          onDelta: (chunk) => {
            acc += chunk
            void aiStore.updateChatMessage(assistantId, { content: acc })
          },
        })
        if (res.skill) {
          await aiStore.updateChatMessage(assistantId, { content: `${skillIcon(res.skill)} ${res.answer}` })
          await scrollToBottom()
          return
        }
        reusedAssistantId = assistantId
      } catch {
        /* skill 失败则回落到普通 LLM 对话 */
      }
    }
    const context = buildChatContext(aiStore.chatMessages.map((m) => ({ role: m.role, content: m.content })))
    const assistantId = reusedAssistantId ?? (await aiStore.addChatMessage({ role: 'assistant', content: '' }))
    let acc = ''
    await chatAIStream(context, {
      max_tokens: aiStore.userConfig.maxTokens,
      temperature: aiStore.userConfig.temperature,
      onDelta: (chunk: string) => {
        acc += chunk
        void aiStore.updateChatMessage(assistantId, { content: acc })
      },
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '发送失败，请稍后重试')
  } finally {
    chatSending.value = false
  }
}
</script>

<template>
  <div class="chat-page">
    <section class="panel chat-hero">
      <div>
        <div class="page-title">AI 对话</div>
        <div class="page-subtitle">
          和弹窗共用同一份对话记录（{{ chatMessages.length === 0 ? '就绪' : `上下文 ${Math.min(chatMessages.length, 8)} 条` }}），在这里可以宽屏长文追问
        </div>
      </div>
      <div class="hero-actions">
        <el-button :icon="Setting" @click="openSettings">生成参数</el-button>
        <el-button :icon="Delete" @click="clearChat">清空记录</el-button>
        <el-tooltip content="退出对话，返回运营助手" placement="bottom">
          <el-button :icon="Close" @click="exitChatPage" />
        </el-tooltip>
      </div>
    </section>

    <section class="panel chat-main">
      <div ref="chatListRef" class="chat-body">
        <div v-if="chatMessages.length === 0" class="chat-empty">
          <div class="chat-empty-title">开始和运营专家聊聊</div>
          <div class="chat-empty-desc">可以把运营助手里的标题 / 文案复制过来，让我给你多几个版本，或针对平台规则再优化。</div>
        </div>
        <div v-for="m in chatMessages" :key="m.id" class="chat-msg" :class="m.role">
          <div class="chat-bubble">
            <div class="chat-text">{{ m.content }}</div>
          </div>
        </div>
        <div v-if="chatSending" class="chat-msg assistant">
          <div class="chat-bubble"><span class="chat-typing">正在生成…</span></div>
        </div>
      </div>
      <div class="chat-input">
        <el-input
          v-model="chatInput"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="给AI助手发送消息吧 ~（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="handleSend"
        />
        <el-button type="primary" :icon="Promotion" :loading="chatSending" :disabled="!chatInput.trim()" @click="handleSend">
          发送
        </el-button>
      </div>
    </section>

    <el-drawer v-model="settingsVisible" title="生成参数设置" direction="rtl" size="300px" :append-to-body="true">
      <div class="settings-body">
        <div class="settings-item">
          <div class="settings-label"><span>最大字数</span><span class="settings-value">{{ maxTokens }}</span></div>
          <el-slider v-model="maxTokens" :min="100" :max="2000" :step="100" :show-tooltip="false" />
        </div>
        <div class="settings-item">
          <div class="settings-label"><span>Temperature</span><span class="settings-value">{{ temperature.toFixed(1) }}</span></div>
          <el-slider v-model="temperature" :min="0" :max="1" :step="0.1" :show-tooltip="false" />
        </div>
        <el-button type="primary" class="settings-save" @click="applySettings">保存设置</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.chat-page { display: flex; flex-direction: column; gap: 20px; }
.chat-hero { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.hero-actions { display: flex; gap: 8px; }
.chat-main { display: flex; flex-direction: column; min-height: 560px; max-height: calc(100vh - 320px); overflow: hidden; }
.chat-body { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 12px; padding: 16px 4px;}
.chat-empty { margin: auto; text-align: center; color: var(--text-muted); }
.chat-empty-title { font-size: 16px; font-weight: 600; color: #0f172a; margin-bottom: 6px; }
.chat-msg { display: flex; }
.chat-msg.user { justify-content: flex-end; }
.chat-msg.assistant { justify-content: flex-start; }
.chat-bubble { max-width: 75%; border-radius: 14px; padding: 10px 14px; background: #f9fafb; box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06); }
.chat-msg.user .chat-bubble { background: rgba(59, 130, 246, 0.12); }
.chat-text { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.8; color: #111827; }
.chat-typing { font-size: 13px; color: var(--text-muted); }
.chat-input { padding: 12px 4px 4px; border-top: 1px solid rgba(15, 23, 42, 0.06); display: flex; gap: 10px; align-items: flex-end; }
.settings-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 24px; }
.settings-item { display: flex; flex-direction: column; gap: 10px; }
.settings-label { display: flex; justify-content: space-between; font-size: 14px; font-weight: 500; color: #1f2d3d; }
.settings-value { font-size: 13px; color: var(--el-color-primary); font-weight: 600; }
.settings-save { width: 100%; }
</style>
