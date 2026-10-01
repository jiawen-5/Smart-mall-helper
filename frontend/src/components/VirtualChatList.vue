<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { ChatMessageItem } from '@/stores/aiDb'
import { isNearBottom } from '@/utils/markdownSafe'
import MarkdownRender from '@/components/MarkdownRender.vue'

const props = withDefaults(
  defineProps<{
    messages: ChatMessageItem[]
    typingText?: string | null
    hasMore?: boolean
    loadingMore?: boolean
    bodyClass?: string
  }>(),
  { typingText: null, hasMore: false, loadingMore: false, bodyClass: '' },
)
const emit = defineEmits<{ (e: 'load-more'): void; (e: 'stick-change', sticking: boolean): void }>()

const scrollRef = ref<HTMLElement | null>(null)
const sticking = ref(true)

const onScroll = () => {
  const el = scrollRef.value
  if (!el) return
  sticking.value = isNearBottom(el, 80)
  emit('stick-change', sticking.value)
  if (el.scrollTop < 160 && props.hasMore && !props.loadingMore) emit('load-more')
}

const scrollToBottom = async (force = false) => {
  const el = scrollRef.value
  if (!el) return
  if (!force && !isNearBottom(el, 80)) return
  for (let i = 0; i < 3; i++) {
    await nextTick()
    el.scrollTop = el.scrollHeight
  }
  sticking.value = true
}

onMounted(() => {
  void scrollToBottom(true)
})

watch(
  () => props.messages.length,
  async (n, prev) => {
    if (n === prev) return
    if (n > prev && sticking.value) await scrollToBottom(true)
  },
)

defineExpose({ scrollToBottom, scrollElement: scrollRef })
</script>

<template>
  <div ref="scrollRef" :class="bodyClass" @scroll="onScroll" style="position: relative">
    <div v-if="hasMore || loadingMore" class="load-more-row">
      <span v-if="loadingMore" class="load-more-text">正在加载更早的消息…</span>
      <span v-else class="load-more-text">上滑加载更早的消息</span>
    </div>
    <div v-if="messages.length === 0 && !typingText" class="chat-empty-slot">
      <slot name="empty" />
    </div>
    <div v-for="m in messages" :key="m.id" class="chat-msg" :class="m.role">
      <div class="chat-bubble">
        <MarkdownRender v-if="m.role === 'assistant'" :content="m.content" />
        <div v-else class="chat-text">{{ m.content }}</div>
      </div>
    </div>
    <div v-if="typingText" class="chat-msg assistant">
      <div class="chat-bubble">
        <span class="chat-typing">{{ typingText }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.load-more-row {
  display: flex;
  justify-content: center;
  padding: 6px 0 2px;
}
.load-more-text {
  font-size: 12px;
  color: var(--text-muted);
}
.chat-msg {
  display: flex;
  padding: 5px 10px;
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
  font-size: 13px;
  color: #111827;
  line-height: 1.7;
}
.chat-typing {
  font-size: 12px;
  color: var(--text-muted);
}
.chat-empty-slot {
  padding: 24px 12px;
  text-align: center;
  color: var(--text-muted);
}
</style>
