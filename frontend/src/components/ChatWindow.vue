<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useApi } from '@/composables/useApi'
import ChatMessage from './ChatMessage.vue'

const chatStore = useChatStore()
const api = useApi()
const inputValue = ref('')
const isLoading = ref(false)

async function handleSend() {
  const text = inputValue.value.trim()
  if (!text || isLoading.value) return

  inputValue.value = ''
  chatStore.addMessage('user', text)
  isLoading.value = true

  try {
    const response = await api.chat({ message: text, stream: false })
    chatStore.addMessage('assistant', response.response)
  } catch (e) {
    chatStore.addMessage('assistant', `抱歉，发生错误：${(e as Error).message}`)
  } finally {
    isLoading.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

watch(
  () => chatStore.messages.length,
  () => {
    nextTick(() => {
      const container = document.querySelector('.chat-messages')
      if (container) {
        container.scrollTop = container.scrollHeight
      }
    })
  }
)
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="chat-messages flex-1 overflow-y-auto p-6 space-y-4">
      <div v-if="chatStore.messages.length === 0" class="flex items-center justify-center h-full">
        <div class="text-center text-muted-foreground">
          <p class="text-lg mb-2">你好，我是贾维斯</p>
          <p class="text-sm">有什么可以帮你的？</p>
        </div>
      </div>

      <ChatMessage
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
      />

      <div v-if="isLoading" class="flex items-center gap-2 text-muted-foreground">
        <div class="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
        <div class="w-2 h-2 rounded-full bg-primary animate-pulse delay-75"></div>
        <div class="w-2 h-2 rounded-full bg-primary animate-pulse delay-150"></div>
        <span class="text-sm">贾维斯正在思考...</span>
      </div>
    </div>

    <div class="p-4 border-t border-border">
      <div class="flex gap-3">
        <input
          v-model="inputValue"
          type="text"
          placeholder="输入消息..."
          class="flex-1 bg-secondary rounded-full px-4 py-3 text-sm outline-none focus:ring-2 ring-ring transition-shadow"
          :disabled="isLoading"
          @keydown="handleKeydown"
        >
        <button
          class="btn btn-primary"
          :disabled="isLoading || !inputValue.trim()"
          @click="handleSend"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn {
  @apply w-12 h-12 rounded-full border-none flex items-center justify-center cursor-pointer transition-all;
}
.btn-primary {
  @apply bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed;
}
.animate-pulse {
  animation: pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
.delay-75 {
  animation-delay: 75ms;
}
.delay-150 {
  animation-delay: 150ms;
}
</style>