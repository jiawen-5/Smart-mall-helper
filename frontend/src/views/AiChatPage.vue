<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close, Promotion, Setting, Delete } from '@element-plus/icons-vue'
import { buildChatContext, chatAIStream } from '@/utils/aiApi'
import { routeSkill, streamProductMetrics, streamCopywriting, streamCustomerService, skillIcon } from '@/utils/backendApi'
import { selectByTokenBudget, CONTEXT_TOKEN_BUDGET } from '@/utils/contextBudget'
import VirtualChatList from '@/components/VirtualChatList.vue'
import { useAIStore } from '@/stores/aiStore'
import { createStreamBuffer } from '@/utils/streamBuffer'
import { statusLabel } from '@/utils/chatStatus'

const router = useRouter()
const aiStore = useAIStore()

const exitChatPage = () => {
  router.push('/assistant')
}
const chatInput = ref('')
const chatSending = ref(false)
const settingsVisible = ref(false)

const maxTokens = ref(aiStore.userConfig.maxTokens)
const temperature = ref(aiStore.userConfig.temperature)

const chatMessages = computed(() => aiStore.chatMessages)

// token 预算内实际会带上的上下文（与 buildChatContext 同口径，不再固定 8 条）
const contextInfo = computed(() => {
  const all = chatMessages.value.map((m) => ({ role: m.role, content: m.content || '' }))
  const { kept, usedTokens } = selectByTokenBudget(all, CONTEXT_TOKEN_BUDGET)
  void kept
  return { count: all.length, usedTokens }
})

const scrollToBottom = async (force = false) => {
  await listRef.value?.scrollToBottom(force)
}

const onStickChange = (sticking: boolean) => {
  showBackToBottom.value = !sticking
}

const listRef = ref<{ scrollToBottom: (force?: boolean) => Promise<void>; scrollElement?: { value?: unknown } | unknown } | null>(null)

// 顶部加载更多：游标分页向前读 20 条，并补偿 scrollHeight 防止跳动
const handleLoadMore = async () => {
  const raw = listRef.value?.scrollElement as { value?: unknown } | HTMLElement | undefined
  const el = (raw && typeof raw === 'object' && 'value' in (raw as object)
    ? (raw as { value?: unknown }).value
    : raw) as HTMLElement | undefined
  const prevHeight = el?.scrollHeight ?? 0
  const added = await aiStore.loadOlderChatMessages()
  if (added > 0 && el) {
    await nextTick()
    el.scrollTop += el.scrollHeight - prevHeight
  }
}

const showBackToBottom = ref(false)

watch(
  () => chatMessages.value.length,
  () => void scrollToBottom()
)

onMounted(async () => {
  await aiStore.ensureHydrated().catch(() => {})
  maxTokens.value = aiStore.userConfig.maxTokens
  temperature.value = aiStore.userConfig.temperature
  void scrollToBottom(true)
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
  aiStore.setChatStatus('thinking')
  await aiStore.addChatMessage({ role: 'user', content })
  chatInput.value = ''
  void scrollToBottom(true)

  try {
    // 先轻量路由（/agent/route），再按 skill 打对应流式接口，保证网络面板可区分：
    // chat-stream（闲聊）/ product-metrics / copywriting / customer-service
    const history = aiStore.chatMessages.slice(0, -1).map((m) => ({ role: m.role, content: m.content }))
    const routed = await routeSkill(content, history).catch(() => ({ skill: null as string | null }))
    const assistantId = await aiStore.addChatMessage({ role: 'assistant', content: '' })
    const buf = createStreamBuffer((text) => {
      aiStore.patchChatMessageContent(assistantId, text)
      void scrollToBottom()
    })
    const onStatus = (s: string) => {
      if (s === 'tool_calling') aiStore.setChatStatus('tool_calling')
      else if (s === 'answering') aiStore.setChatStatus('answering')
    }
    let res: { skill: string | null; answer: string }
    if (routed.skill === 'product_metrics') {
      aiStore.setChatStatus('tool_calling')
      res = await streamProductMetrics(content, { history, onDelta: (c) => buf.push(c), onStatus })
    } else if (routed.skill === 'copywriting') {
      aiStore.setChatStatus('tool_calling')
      res = await streamCopywriting({ question: content, history }, { onDelta: (c) => buf.push(c), onStatus })
    } else if (routed.skill === 'customer_service') {
      aiStore.setChatStatus('tool_calling')
      const orderMatch = content.match(/(?:订单号|订单|order[_ ]?id)\s*[:：]?\s*([A-Za-z0-9\-_]{6,40})/i)
      res = await streamCustomerService(
        { question: content, history, order_id: orderMatch ? orderMatch[1] : undefined },
        { onDelta: (c) => buf.push(c), onStatus },
      )
    } else {
      // 大模型流式：thinking → answering，上下文 2000 token（后端裁剪）
      const context = buildChatContext(aiStore.chatMessages.slice(0, -1).map((m) => ({ role: m.role, content: m.content })))
      res = { skill: null, answer: '' }
      await chatAIStream(context, {
        max_tokens: aiStore.userConfig.maxTokens,
        temperature: aiStore.userConfig.temperature,
        onDelta: (c: string) => buf.push(c),
        onStatus: (s) => aiStore.setChatStatus(s === 'answering' ? 'answering' : 'thinking'),
      })
    }
    buf.flushNow()
    if (res.skill) {
      await aiStore.updateChatMessage(assistantId, { content: `${skillIcon(res.skill)} ${res.answer || aiStore.chatMessages.find((m) => m.id === assistantId)?.content || ''}` })
    }
    await aiStore.persistChatMessage(assistantId)
    await scrollToBottom(true)
  } catch (error) {
    aiStore.forceChatStatus('error')
    ElMessage.error(error instanceof Error ? error.message : '发送失败，请稍后重试')
  } finally {
    chatSending.value = false
    aiStore.forceChatStatus('idle')
  }
}
</script>

<template>
  <div class="chat-page">
    <section class="panel chat-hero">
      <div>
        <div class="page-title">AI 对话</div>
        <div class="page-subtitle">
          和弹窗共用同一份对话记录，在这里可以宽屏长文追问
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
      <VirtualChatList
        ref="listRef"
        body-class="chat-body virtual-body"
        :messages="chatMessages"
        :typing-text="chatSending ? (statusLabel(aiStore.chatStatus) || '正在生成…') : null"
        :has-more="aiStore.chatHasMore"
        :loading-more="aiStore.chatLoadingMore"
        @load-more="handleLoadMore"
        @stick-change="onStickChange"
      >
        <template #empty>
          <div class="chat-empty-title">开始和运营专家聊聊</div>
          <div class="chat-empty-desc">可以把运营助手里的标题 / 文案复制过来，让我给你多几个版本，或针对平台规则再优化。</div>
        </template>
      </VirtualChatList>
      <el-button v-if="showBackToBottom" class="back-bottom-float" size="small" round @click="scrollToBottom(true)">回到底部</el-button>
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
.chat-body { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 12px; padding: 16px 4px; position: relative; }
.virtual-body { display: block; }
.back-bottom-float { position: absolute; left: 50%; bottom: 90px; transform: translateX(-50%); z-index: 5; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18); }
.chat-main { position: relative; }
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
