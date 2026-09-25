<script setup lang="ts">
import { reactive, ref, onMounted, computed, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound , Close, Loading } from '@element-plus/icons-vue'
import { buildChatContext, chatAIStream, type ChatMessage, optimizeProductTitle, generateMarketingCopy, generateCustomerServiceReply } from '@/utils/aiApi'
import { useAIStore } from '@/stores/aiStore'
import AiChat from './AiChat.vue'
import type { ChatItem } from './AiChat.vue'

const aiStore = useAIStore()

// “猜你想问”建议问题（短、命中查询类 Skill）
const suggestQuestions = [
  '本月 GMV 是多少？',
  '本月环比上月怎么样？',
]
const suggestVisible = ref(true)
const chatRef = ref<{ sendMessage: (text?: string) => void } | null>(null)

const useSuggestion = (q: string) => {
  suggestVisible.value = false
  chatRef.value?.sendMessage(q)
}
const historyVisible = ref(false)
const historyFilter = ref<'all' | 'title' | 'copy' | 'qa'>('all')

const filteredHistory = computed(() => {
  if (historyFilter.value === 'all') return aiStore.history
  return aiStore.history.filter((item) => item.type === historyFilter.value)
})

const titleForm = reactive({
  original: '夏日清爽真丝衬衫 女士通勤百搭',
  keywords: '真丝,透气,通勤,新品',
})

const copyForm = reactive({
  product: '智能恒温杯 · 500ml',
  highlights: '保温12小时|食品级内胆|一键测温',
  tone: aiStore.userConfig.tone,
})

const qaForm = reactive({
  question: '保温时长多久？杯子会发烫吗？',
})

const optimizedTitle = ref('')
const generatedCopy = ref('')

type Suggestion = {
  question: string
  answer: string
}

const suggestions = ref<Suggestion[]>([])

const titleLoading = ref(false)
const copyLoading = ref(false)
const qaLoading = ref(false)

// 浮动对话框状态
const chatVisible = ref(false)
const chatInput = ref('')
const chatSending = ref(false)
const chatListRef = ref<HTMLElement | null>(null)

const chatMessages = computed(() => aiStore.chatMessages)

const scrollChatToBottom = async () => {
  await nextTick()
  const el = chatListRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => chatMessages.value.length,
  () => {
    if (!chatVisible.value) return
    void scrollChatToBottom()
  }
)

const openChat = (seed?: string) => {
  chatVisible.value = true
  if (seed && seed.trim()) {
    chatInput.value = `基于下面内容继续优化/改写，给 2-3 个版本：\n${seed.trim()}`
  }
  void scrollChatToBottom()
}

const handleChatSend = async () => {
  const content = chatInput.value.trim()
  if (!content || chatSending.value) return

  chatSending.value = true
  await aiStore.addChatMessage({ role: 'user', content })
  chatInput.value = ''

  try {
    const context: ChatMessage[] = buildChatContext(
      aiStore.chatMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }))
    )
    const assistantId = await aiStore.addChatMessage({ role: 'assistant', content: '' })
    let acc = ''
    await chatAIStream(context, {
      max_tokens: aiStore.userConfig.maxTokens,
      temperature: aiStore.userConfig.temperature,
      onDelta: (chunk: string) => {
        acc += chunk
        aiStore.updateChatMessage(assistantId, { content: acc })
      },
    })
  } catch (error) {
    ElMessage.error(getErrorMessage(error) || '发送失败，请稍后重试')
  } finally {
    chatSending.value = false
  }
}

const getErrorMessage = (err: unknown) => {
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  return 'AI服务暂时不可用，请稍后重试'
}

// 标题优化 - 连接真实AI
const handleTitleGenerate = async () => {
  if (!titleForm.original.trim()) {
    ElMessage.warning('请输入商品标题')
    return
  }

  titleLoading.value = true
  optimizedTitle.value = '' 
  try {
    const result = await optimizeProductTitle(titleForm.original, titleForm.keywords)
    optimizedTitle.value = result
    ElMessage.success('标题优化成功！')
    aiStore.addHistory({
      type: 'title',
      input: `${titleForm.original} | ${titleForm.keywords}`,
      output: result,
    })
  } catch (error) {
    console.error('标题优化失败:', error)
    ElMessage.error(getErrorMessage(error) || '优化失败，请检查API密钥或网络连接')
    // 降级方案
    optimizedTitle.value = `【AI优化】${titleForm.original} - ${titleForm.keywords.split(',').join(' · ')}`
  } finally {
    titleLoading.value = false
  }
}

// 文案生成 - 连接真实AI
const handleCopyGenerate = async () => {
  if (!copyForm.product.trim()) {
    ElMessage.warning('请输入商品信息')
    return
  }

  copyLoading.value = true
  generatedCopy.value = '' // 清空之前的结果
  
  try {
    const result = await generateMarketingCopy(copyForm.product, copyForm.highlights, copyForm.tone)
    generatedCopy.value = result
    ElMessage.success('文案生成成功！')
    aiStore.addHistory({
      type: 'copy',
      input: `${copyForm.product} | ${copyForm.highlights} | ${copyForm.tone}`,
      output: result,
    })
  } catch (error) {
    console.error('文案生成失败:', error)
    ElMessage.error(getErrorMessage(error) || '生成失败，请检查API密钥或网络连接')
    // 降级方案
    generatedCopy.value = `${copyForm.tone}风格推荐：${copyForm.product}，${copyForm.highlights}。适合社交媒体推广使用。`
  } finally {
    copyLoading.value = false
  }
}

// 客服话术 - 连接真实AI
const handleQaGenerate = async () => {
  if (!qaForm.question.trim()) {
    ElMessage.warning('请输入客户问题')
    return
  }

  qaLoading.value = true
  try {
    const answer = await generateCustomerServiceReply(qaForm.question)
    // 添加到建议列表顶部
    suggestions.value.unshift({
      question: qaForm.question,
      answer: answer
    })
    aiStore.addHistory({
      type: 'qa',
      input: qaForm.question,
      output: answer,
    })
    
    // 只保留最新的3条
    if (suggestions.value.length > 3) {
      suggestions.value = suggestions.value.slice(0, 3)
    }
    
    ElMessage.success('回复生成成功！')
    qaForm.question = '' // 清空输入框
  } catch (error) {
    console.error('客服回复生成失败:', error)
    ElMessage.error(getErrorMessage(error) || '生成失败，请检查API密钥或网络连接')
    // 降级方案
    suggestions.value.unshift({
      question: qaForm.question,
      answer: '感谢您的咨询！我们的产品具有优质的性能和完善的售后服务，具体问题我们的客服专员会尽快为您解答。'
    })
  } finally {
    qaLoading.value = false
  }
}

// 页面加载时显示使用提示
onMounted(async () => {
  await aiStore.ensureHydrated().catch(() => {})
  copyForm.tone = aiStore.userConfig.tone
  optimizedTitle.value = '请输入标题并点击"一键生成"获取AI优化结果'
  generatedCopy.value = '请输入商品信息并点击"生成文案"获取AI创作内容'
  
  // 初始化一些示例问答
  suggestions.value = [
    {
      question: '商品什么时候发货？',
      answer: '请输入问题并点击"生成回复"获取AI建议'
    }
  ]
})
</script>

<template>
  <div class="assistant-page">
    <section class="panel hero">
      <div>
        <div class="page-title">AI 运营助手</div>
        <div class="page-subtitle">基于商品与用户画像，秒级生成标题、文案与客服话术</div>
      </div>
      <div class="hero-actions">
        <el-tag type="success" effect="dark">已连接私有大模型</el-tag>
        <el-button type="primary" link @click="historyVisible = true">查看历史</el-button>
      </div>
    </section>

    <!-- 标题生成 -->
    <el-row :gutter="20">
      <el-col :xs="24" :md="12" :xl="8">
        <section class="panel tool-panel">
          <div class="section-title">商品标题优化</div>
          <p class="tag-muted">智能拆解卖点，自动组合高转化关键词</p>
          <el-form :model="titleForm" label-position="top">
            <el-form-item label="原始标题">
              <el-input v-model="titleForm.original" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="关键卖点/关键词（逗号分隔）">
              <el-input v-model="titleForm.keywords" />
            </el-form-item>
          </el-form>
          <el-button 
            type="primary" 
            @click="handleTitleGenerate"
            :loading="titleLoading"
            :disabled="!titleForm.original.trim()"
          >
            {{ titleLoading ? 'AI优化中...' : '一键生成' }}
          </el-button>
          <el-divider />
          <div class="result-box">
            <div class="result-label">推荐标题</div>
            <div v-if="titleLoading" class="loading-placeholder">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>AI正在优化标题...</span>
            </div>
            <div v-else>
              <p>{{ optimizedTitle || '请输入标题并点击生成' }}</p>
              <div v-if="optimizedTitle && !optimizedTitle.includes('请输入')" class="result-actions">
                <el-button size="small" link type="primary" @click="openChat(optimizedTitle)">继续对话优化</el-button>
              </div>
            </div>
          </div>
        </section>
      </el-col>

      <!-- 营销文案 -->
      <el-col :xs="24" :md="12" :xl="8">
        <section class="panel tool-panel">
          <div class="section-title">营销文案生成</div>
          <p class="tag-muted">平衡人设、卖点与行动号召</p>
          <el-form :model="copyForm" label-position="top">
            <el-form-item label="商品名称">
              <el-input v-model="copyForm.product" />
            </el-form-item>
            <el-form-item label="核心卖点">
              <el-input v-model="copyForm.highlights" />
            </el-form-item>
            <el-form-item label="想要的语气">
              <el-select v-model="copyForm.tone">
                <el-option label="活力年轻" value="活力年轻" />
                <el-option label="专业权威" value="专业权威" />
                <el-option label="温暖治愈" value="温暖治愈" />
              </el-select>
            </el-form-item>
          </el-form>
          <el-button 
            type="primary" 
            @click="handleCopyGenerate"
            :loading="copyLoading"
            :disabled="!copyForm.product.trim()"
          >
            {{ copyLoading ? '生成中...' : '生成文案' }}
          </el-button>
          <div class="result-box">
            <div class="result-label">推荐文案</div>
            <div v-if="copyLoading" class="loading-placeholder">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>AI正在创作文案...</span>
            </div>
            <div v-else>
              <p>{{ generatedCopy || '请输入商品信息并点击生成' }}</p>
              <div v-if="generatedCopy && !generatedCopy.includes('请输入')" class="result-actions">
                <el-button size="small" link type="primary" @click="openChat(generatedCopy)">继续对话改写</el-button>
              </div>
            </div>
          </div>
        </section>
      </el-col>

      <!-- 客服回答 -->
      <el-col :xs="24" :md="12" :xl="8">
        <section class="panel tool-panel">
          <div class="section-title">客服话术建议</div>
          <p class="tag-muted">覆盖常见问题，统一服务体验</p>
          <el-form :model="qaForm" label-position="top">
            <el-form-item label="客户问题">
              <el-input v-model="qaForm.question" type="textarea" :rows="2" />
            </el-form-item>
          </el-form>
          <el-button 
            type="primary" 
            @click="handleQaGenerate"
            :loading="qaLoading"
            :disabled="!qaForm.question.trim()"
          >
            {{ qaLoading ? '生成中...' : '生成回复' }}
          </el-button>
          <el-divider />
          <div class="qa-list">
            <div v-for="item in suggestions" :key="item.question" class="qa-item">
              <div class="qa-question">{{ item.question }}</div>
              <div class="qa-answer">{{ item.answer }}</div>
            </div>
          </div>
        </section>
      </el-col>
    </el-row>

    <!-- ai生成 历史记录 -->
    <el-dialog v-model="historyVisible" title="AI 生成历史" width="720px">
      <template #default>
        <div class="history-filter">
          <el-segmented
            v-model="historyFilter"
            :options="[
              { label: '全部', value: 'all' },
              { label: '标题', value: 'title' },
              { label: '文案', value: 'copy' },
              { label: '客服', value: 'qa' },
            ]"
          />
        </div>
        <el-table :data="filteredHistory" height="360" stripe>
          <el-table-column prop="type" label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.type === 'title' ? 'primary' : row.type === 'copy' ? 'success' : 'info'">
                {{ row.type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="input" label="输入" min-width="180" show-overflow-tooltip />
          <el-table-column prop="output" label="输出" min-width="260" show-overflow-tooltip />
          <el-table-column prop="createdAt" label="时间" width="140">
            <template #default="{ row }">
              {{ new Date(row.createdAt).toLocaleString() }}
            </template>
          </el-table-column>
        </el-table>
        <template v-if="filteredHistory.length === 0">
          <el-empty description="暂无历史记录" />
        </template>
      </template>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="historyVisible = false">关闭</el-button>
          <el-button type="danger" text @click="aiStore.clearHistory()">清空历史</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 悬浮对话框 -->
    <div v-if="suggestVisible" class="suggest-pop">
      <div class="suggest-header">
        <span class="suggest-title">猜你想问</span>
        <el-button :icon="Close" circle link size="small" @click="suggestVisible = false" />
      </div>
      <button v-for="q in suggestQuestions" :key="q" class="suggest-item" type="button" @click="useSuggestion(q)">
        {{ q }}
      </button>
    </div>
    <div class="floating-ball">
      <el-button class="floating-btn" type="primary" circle :icon="ChatDotRound" @click="openChat()" />
      <div class="floating-hint">对话</div>
    </div>

    <AiChat ref="chatRef" v-model:visible="chatVisible" :messages="chatMessages" :standalone="false" />
  </div>
</template>

<style scoped>
.el-col{
  margin-bottom: 20px;
}

.loading-placeholder {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-color-primary);
  padding: 20px 0;
  justify-content: center;
}

.loading-placeholder .el-icon {
  font-size: 16px;
}

.assistant-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.page-subtitle {
  margin-bottom: 0;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-panel {
  min-height: 420px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-box {
  background: #f7faff;
  border-radius: 12px;
  padding: 12px 16px;
  color: #1f2d3d;
  box-shadow: inset 0 0 0 1px #dbe4f3;
}

.result-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.result-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}

.qa-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.qa-item {
  background: #fef6ee;
  border-radius: 12px;
  padding: 12px 14px;
  border: 1px solid #ffe1c8;
}

.qa-question {
  font-weight: 600;
  margin-bottom: 4px;
}

.qa-answer {
  color: var(--text-muted);
}

.history-filter {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

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

.suggest-pop {
  position: fixed;
  right: 26px;
  bottom: 120px;
  z-index: 55;
  width: 200px;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.18);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggest-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px;
}

.suggest-title {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.suggest-item {
  text-align: left;
  border: none;
  background: #fff;
  color: #334155;
  font-size: 13px;
  padding: 3px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.suggest-item:hover {
  background: rgba(63, 140, 255, 0.12);
  color: #1d4ed8;
}
</style>

