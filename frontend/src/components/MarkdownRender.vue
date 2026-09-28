<script setup lang="ts">
import { computed } from 'vue'
import { renderSafeMarkdown } from '@/utils/markdownSafe'

const props = defineProps<{ content: string; streaming?: boolean }>()

// 流式时父组件已用 rAF 节流，这里纯计算 + v-html 一次，配合 sanitize 无布局抖动
const html = computed(() => renderSafeMarkdown(props.content))
</script>

<template>
  <div class="md-body" v-html="html"></div>
</template>

<style scoped>
.md-body {
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
  overflow-wrap: anywhere;
  min-height: 1.4em;
}
.md-body:deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
  overflow: auto;
  max-width: 100%;
}
.md-body:deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.md-body:deep(table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.md-body:deep(th),
.md-body:deep(td) {
  border: 1px solid rgba(15, 23, 42, 0.12);
  padding: 4px 6px;
  text-align: left;
}
</style>
