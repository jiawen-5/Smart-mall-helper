<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
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

const virtualizer = useVirtualizer({
  count: props.messages.length,
  getScrollElement: () => scrollRef.value,
  estimateSize: () => 110,
  overscan: 6,
})

// 必须用 computed 包一层：getVirtualItems() 依赖滚动位置 + 测量缓存，直接存 const 不会更新
const items = computed(() => virtualizer.value.getVirtualItems())
const totalSize = computed(() => virtualizer.value.getTotalSize())

const onScroll = () => {
  const el = scrollRef.value
  if (!el) return
  sticking.value = isNearBottom(el, 80)
  emit('stick-change', sticking.value)
  // 滚动到顶部：触发游标加载下一页
  if (el.scrollTop < 160 && props.hasMore && !props.loadingMore) emit('load-more')
}

const scrollToBottom = async (force = false) => {
  const el = scrollRef.value
  if (!el) return
  if (!force && !isNearBottom(el, 80)) return
  // 虚拟列表初挂载时行高全是估算值，scrollHeight 会连跳几次，多刷几帧确保真正到底
  for (let i = 0; i < 3; i++) {
    await nextTick()
    el.scrollTop = el.scrollHeight
  }
  sticking.value = true
}

// 初次挂载直接钉到底部（最新消息），而不是停在顶部
onMounted(() => {
  void scrollToBottom(true)
})

// 新消息到达：贴底时跟随，否则保持位置（顶部加载时由调用方做 scrollHeight 补偿）
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
    <div
      :style="{ height: `${totalSize}px`, width: '100%', position: 'relative' }"
    >
      <div
        v-for="row in items"
        :key="messages[row.index]!.id"
        :data-index="row.index"
        :ref="(el) => (el as HTMLElement | null) && virtualizer.measureElement(el as HTMLElement)"
        :style="{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          transform: `translateY(${row.start}px)`,
        }"
      >
        <div class="chat-msg" :class="messages[row.index]!.role">
          <div class="chat-bubble">
            <MarkdownRender v-if="messages[row.index]!.role === 'assistant'" :content="messages[row.index]!.content" />
            <div v-else class="chat-text">{{ messages[row.index]!.content }}</div>
          </div>
        </div>
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
