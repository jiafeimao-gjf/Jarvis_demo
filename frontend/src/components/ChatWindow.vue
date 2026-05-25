<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useApi } from '@/composables/useApi'
import ChatMessage from './ChatMessage.vue'

const chatStore = useChatStore()
const api = useApi()
const inputValue = ref('')
const isLoading = ref(false)
const currentResponse = ref('')

async function handleSend() {
  const text = inputValue.value.trim()
  if (!text || isLoading.value) return

  inputValue.value = ''
  chatStore.addMessage('user', text)
  isLoading.value = true
  currentResponse.value = ''

  try {
    // Add empty assistant message that we'll update
    chatStore.addMessage('assistant', '')
    const msgIndex = chatStore.messages.length - 1

    // Use streaming API
    await api.chatStream(
      { message: text, stream: true },
      (token: string) => {
        currentResponse.value += token
        // Update the last message with streaming content
        if (chatStore.messages[msgIndex]) {
          chatStore.messages[msgIndex].content = currentResponse.value
        }
      },
      () => {
        // Done
        isLoading.value = false
      }
    )
  } catch (e) {
    chatStore.addMessage('assistant', `抱歉，发生错误：${(e as Error).message}`)
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

      <div v-if="isLoading" class="flex items-center gap-2">
        <div class="typing-indicator">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span class="text-sm text-muted-foreground">贾维斯正在思考...</span>
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
          <svg v-if="!isLoading" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
          </svg>
          <svg v-else class="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
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
.animate-spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.typing-indicator {
  display: inline-flex;
  gap: 4px;
  padding: 8px 12px;
  background: var(--secondary);
  border-radius: 16px;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--primary);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}
.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>