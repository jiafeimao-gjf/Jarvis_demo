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
      'flex flex-col px-4 py-3 max-w-[70%] break-words',
      isUser
        ? 'items-end self-end'
        : 'items-start self-start'
    ]"
  >
    <!-- Chat bubble -->
    <div
      :class="[
        'rounded-2xl px-4 py-3 relative',
        isUser
          ? 'bg-gradient-to-br from-primary/30 to-primary/10 border border-primary/30'
          : 'bg-gradient-to-br from-secondary/80 to-secondary/40 border border-primary/20'
      ]"
      :style="isUser ? 'clip-path: polygon(0 0, 100% 0, 100% 85%, 85% 100%, 0 100%);' : 'clip-path: polygon(0 0, 100% 0, 100% 100%, 15% 100%, 0 85%);'"
    >
      <!-- User message: plain text -->
      <p v-if="isUser" class="text-sm leading-relaxed whitespace-pre-wrap text-foreground">{{ message.content }}</p>
      <!-- Assistant message: rendered markdown -->
      <div v-else class="text-sm leading-relaxed markdown-content text-foreground" v-html="renderedContent"></div>
    </div>

    <span
      :class="[
        'text-[10px] mt-1 tracking-wider',
        isUser ? 'text-primary/60 text-right' : 'text-primary/40 text-left'
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
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid hsl(var(--primary) / 0.2);
  border-radius: 0.5rem;
  padding: 0.75rem;
  margin: 0.5rem 0;
  overflow-x: auto;
  font-family: ui-monospace, monospace;
  font-size: 0.8em;
}

.markdown-content :deep(code) {
  font-family: ui-monospace, monospace;
  font-size: 0.875em;
  background: rgba(0, 0, 0, 0.2);
  padding: 0.15em 0.4em;
  border-radius: 0.25rem;
}

.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
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
  color: hsl(var(--primary));
  text-decoration: underline;
}

.markdown-content :deep(blockquote) {
  border-left: 3px solid hsl(var(--primary) / 0.5);
  padding-left: 0.75rem;
  margin: 0.5rem 0;
  opacity: 0.8;
}

.markdown-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5rem 0;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid hsl(var(--border));
  padding: 0.5rem;
}

.markdown-content :deep(th) {
  background: hsl(var(--primary) / 0.1);
}
</style>