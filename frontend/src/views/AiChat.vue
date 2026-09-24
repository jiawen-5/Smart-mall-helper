<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Close, FullScreen, Promotion, Setting } from '@element-plus/icons-vue'
import { buildChatContext, chatAIStream } from '@/utils/aiApi'
import { askAgentSkillStream, looksLikeSkillQuery, skillIcon } from '@/utils/backendApi'
import { useAIStore } from '@/stores/aiStore'
import type { ChatMessageItem } from '@/stores/aiDb'

export type ChatItem = ChatMessageItem

const props = withDefaults(
  defineProps<{ visible?: boolean; messages?: ChatItem[]; standalone?: boolean }>(),
  { visible: false, messages: undefined, standalone: true }
)
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'send'): void }>()

const aiStore = useAIStore()
const router = useRouter()

const goFullPage = () => {
  closeChat()
  if (router.currentRoute.value.path !== '/assistant/chat') {
    void router.push('/assistant/chat')
  }
}
// 受控模式（被 AiOperationAssistant 嵌入时）直接用传入的 visible/messages，否则用内部状态
const innerVisible = ref(false)
const chatVisible = computed({
  get: () => (props.messages !== undefined ? props.visible : innerVisible.value),
  set: (v: boolean) => {
    if (props.messages !== undefined) emit('update:visible', v)
    else innerVisible.value = v
  },
})
const chatInput = ref('')
const chatSending = ref(false)
const chatListRef = ref<HTMLElement | null>(null)
const settingsVisible = ref(false)

const maxTokens = ref(aiStore.userConfig.maxTokens)
const temperature = ref(aiStore.userConfig.temperature)

const openSettings = () => {
  maxTokens.value = aiStore.userConfig.maxTokens
  temperature.value = aiStore.userConfig.temperature
  settingsVisible.value = true
}

const applySettings = async () => {
  await aiStore.updateUserConfig({
    maxTokens: maxTokens.value,
    temperature: temperature.value,
  })
  settingsVisible.value = false
  ElMessage.success('设置已更新')
}

const chatMessages = computed(() => props.messages ?? aiStore.chatMessages)

const scrollChatToBottom = async () => {
  // 弹窗刚打开时 DOM 高度还没稳定，多等两帧再滚，避免停在顶部
  await nextTick()
  requestAnimationFrame(() => {
    const el = chatListRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

watch(
  () => chatMessages.value.length,
  () => {
    if (!chatVisible.value) return
    void scrollChatToBottom()
  }
)

// 打开弹窗时直接定位到底部（最新对话），而不是停在顶部
watch(chatVisible, (v) => {
  if (v) void scrollChatToBottom()
})

const openChat = (seed?: string) => {
  chatVisible.value = true
  if (seed && seed.trim()) {
    chatInput.value = `基于下面内容继续优化/改写，给 2-3 个版本：\n${seed.trim()}`
  }
  void scrollChatToBottom()
}

const closeChat = () => {
  chatVisible.value = false
}

const clearChat = () => {
  aiStore.clearChat()
  ElMessage.success('已清空对话历史')
}

const handleChatSend = async () => {
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
          await scrollChatToBottom()
          return
        }
        reusedAssistantId = assistantId
      } catch {
        /* skill 失败则回落到普通 LLM 对话 */
      }
    }
    const context = buildChatContext(
      aiStore.chatMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }))
    )
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
    const msg = error instanceof Error ? error.message : '发送失败，请稍后重试'
    ElMessage.error(msg)
  } finally {
    chatSending.value = false
  }
}

// 供外部（如“猜你想问”）直接以文字打开并发送
const sendMessage = (text?: string) => {
  if (text && text.trim()) chatInput.value = text.trim()
  chatVisible.value = true
  void scrollChatToBottom()
  void nextTick(() => {
    if (chatInput.value.trim()) void handleChatSend()
  })
}

defineExpose({ openChat, closeChat, sendMessage })
</script>

<template>
  <div v-if="standalone" class="floating-ball">
    <el-button class="floating-btn" type="primary" circle :icon="ChatDotRound" @click="openChat()" />
    <div class="floating-hint">对话</div>
  </div>

  <div v-if="chatVisible" class="chat-float">
    <div class="chat-float-header">
      <div class="chat-float-header-row">
        <div class="chat-float-title">AI 对话</div>
        <div class="chat-float-header-right">
          <el-button text size="small" :icon="Setting" @click="openSettings">设置</el-button>
          <el-button text size="small" @click="clearChat">清空</el-button>
          <el-tooltip content="全屏打开" placement="bottom">
            <el-button :icon="FullScreen" circle text @click="goFullPage" />
          </el-tooltip>
          <el-button :icon="Close" circle text @click="closeChat" />
        </div>
      </div>
      <div class="chat-float-subtitle">基于当前运营场景持续追问和改写（{{
        chatMessages.length === 0 ? '就绪' : `上下文 ${Math.min(chatMessages.length, 8)} 条`
      }}）</div>
    </div>
    <div ref="chatListRef" class="chat-float-body">
      <div v-if="chatMessages.length === 0" class="chat-float-empty">
        <div class="chat-float-empty-title">开始和运营专家聊聊</div>
        <div class="chat-float-empty-desc">可以把上面的标题/文案复制过来，让我给你多几个版本或针对平台规则再优化。</div>
      </div>
      <div v-for="m in chatMessages" :key="m.id" class="chat-msg" :class="m.role">
        <div class="chat-bubble">
          <div class="chat-text">{{ m.content }}</div>
        </div>
      </div>
      <div v-if="chatSending" class="chat-msg assistant">
        <div class="chat-bubble">
          <span class="chat-typing">正在生成…</span>
        </div>
      </div>
    </div>
    <div class="chat-float-input">
      <el-input
        v-model="chatInput"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="给AI助手发送消息吧 ~"
        @keydown.enter.exact.prevent="handleChatSend"
      />
      <el-button
        type="primary"
        :icon="Promotion"
        :loading="chatSending"
        :disabled="!chatInput.trim()"
        @click="handleChatSend"
      >
        发送
      </el-button>
    </div>

    <el-drawer
      v-model="settingsVisible"
      title="生成参数设置"
      direction="rtl"
      size="300px"
      :append-to-body="true"
    >
      <div class="settings-body">
        <div class="settings-item">
          <div class="settings-label">
            <span>最大字数</span>
            <span class="settings-value">{{ maxTokens }}</span>
          </div>
          <el-slider
            v-model="maxTokens"
            :min="100"
            :max="2000"
            :step="100"
            :show-tooltip="false"
          />
        </div>
        <div class="settings-item">
          <div class="settings-label">
            <span>Temperature</span>
            <span class="settings-value">{{ temperature.toFixed(1) }}</span>
          </div>
          <el-slider
            v-model="temperature"
            :min="0"
            :max="1"
            :step="0.1"
            :show-tooltip="false"
          />
        </div>
        <div class="settings-desc">
          <p><strong>最大字数</strong>：控制 AI 单次回复的最大长度，值越大回复越详细，但耗时更长。</p>
          <p><strong>Temperature</strong>：控制生成随机性，值越高内容越有创意，值越低内容越稳定。</p>
        </div>
        <el-button type="primary" class="settings-save" @click="applySettings">保存设置</el-button>
      </div>
    </el-drawer>

  </div>
</template>

<style scoped>
.floating-ball {
  position: fixed;
  right: 26px;
  bottom: 26px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.floating-btn {
  width: 52px;
  height: 52px;
  box-shadow: 0 12px 24px rgba(63, 140, 255, 0.32);
}

.floating-hint {
  font-size: 12px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.9);
  padding: 2px 10px;
  border-radius: 999px;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.06);
}

.chat-float {
  position: fixed;
  right: 24px;
  bottom: 96px;
  width: 350px;
  max-width: 100%;
  height: 660px;
  max-height: calc(100vh - 140px);
  background: #ffffff;
  border-radius: 18px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.32);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 60;
}

.chat-float-header {
  padding: 12px 14px 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chat-float-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.chat-float-header-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chat-float-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chat-float-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.chat-float-subtitle {
  font-size: 12px;
  color: var(--text-muted);
}

.chat-float-body {
  flex: 1;
  padding: 10px 10px 6px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: radial-gradient(circle at top left, rgba(148, 163, 184, 0.15), transparent 55%);
}

.chat-float-empty {
  margin: auto;
  text-align: center;
  color: var(--text-muted);
  padding: 0 12px;
}

.chat-float-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}

.chat-float-empty-desc {
  font-size: 12px;
}

.chat-msg {
  display: flex;
}

.chat-msg.user {
  justify-content: flex-end;
}

.chat-msg.assistant {
  justify-content: flex-start;
}

.chat-bubble {
  max-width: 85%;
  border-radius: 14px;
  padding: 8px 10px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06);
  background: #f9fafb;
}

.chat-msg.user .chat-bubble {
  background: rgba(59, 130, 246, 0.12);
}

.chat-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  color: #111827;
  line-height: 1.7;
}

.chat-typing {
  font-size: 12px;
  color: var(--text-muted);
}

.chat-float-input {
  padding: 8px 10px 10px;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  display: flex;
  gap: 8px;
  align-items: flex-end;
  background: #ffffff;
}

@media (max-width: 600px) {
  .chat-float {
    right: 8px;
    left: 8px;
    width: auto;
    height: calc(100vh - 120px);
    bottom: 80px;
  }
}

.settings-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.settings-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.settings-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  font-weight: 500;
  color: #1f2d3d;
}

.settings-value {
  font-size: 13px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.settings-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.8;
}

.settings-desc p {
  margin: 0 0 8px;
}

.settings-save {
  width: 100%;
}

</style>
