<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import { cn } from '@/lib/utils'
import type { Message } from '@/types'
import { formatTime } from '@/lib/utils'

const props = defineProps<{
  message: Message
}>()

const isUser = computed(() => props.message.role === 'user')

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,
  gfm: true
})

// Render markdown content for assistant messages, plain text for user
const renderedContent = computed(() => {
  if (isUser.value) {
    return props.message.content
  }
  return marked.parse(props.message.content) as string
})
</script>

<template>
  <div
    :class="[
      'flex flex-col rounded-2xl px-4 py-3 max-w-[80%] break-words',
      isUser
        ? 'bg-primary text-primary-foreground self-end'
        : 'bg-secondary text-secondary-foreground self-start'
    ]"
  >
    <!-- User message: plain text -->
    <p v-if="isUser" class="text-sm leading-relaxed whitespace-pre-wrap">{{ message.content }}</p>
    <!-- Assistant message: rendered markdown with sanitization -->
    <div v-else class="text-sm leading-relaxed markdown-content" v-html="renderedContent"></div>
    <span
      :class="[
        'text-xs mt-2 opacity-60',
        isUser ? 'text-primary-foreground/70' : 'text-muted-foreground'
      ]"
    >
      {{ formatTime(message.timestamp) }}
    </span>
  </div>
</template>

<style scoped>
.markdown-content {
  word-break: break-word;
}

.markdown-content :deep(pre) {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 0.5rem;
  padding: 0.75rem;
  margin: 0.5rem 0;
  overflow-x: auto;
}

.markdown-content :deep(code) {
  font-family: ui-monospace, monospace;
  font-size: 0.875em;
}

.markdown-content :deep(p:not(:last-child)) {
  margin-bottom: 0.75rem;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.markdown-content :deep(li) {
  margin: 0.25rem 0;
}

.markdown-content :deep(a) {
  color: inherit;
  text-decoration: underline;
}

.markdown-content :deep(blockquote) {
  border-left: 3px solid currentColor;
  opacity: 0.8;
  padding-left: 0.75rem;
  margin: 0.5rem 0;
}
</style>