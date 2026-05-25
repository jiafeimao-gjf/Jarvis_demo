<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'
import type { Message } from '@/types'
import { formatTime } from '@/lib/utils'

const props = defineProps<{
  message: Message
}>()

const isUser = computed(() => props.message.role === 'user')
</script>

<template>
  <div
    :class="[
      'flex flex-col rounded-2xl px-4 py-3 max-w-[70%] break-words',
      isUser
        ? 'bg-primary text-primary-foreground self-end'
        : 'bg-secondary text-secondary-foreground self-start'
    ]"
  >
    <p class="text-sm leading-relaxed whitespace-pre-wrap">{{ message.content }}</p>
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