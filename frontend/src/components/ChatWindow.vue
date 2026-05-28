<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useApi } from '@/composables/useApi'
import ChatMessage from './ChatMessage.vue'

const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const api = useApi()
const inputValue = ref('')
const isLoading = ref(false)
const thinkingStatus = ref('thinking') // 'thinking' | 'typing' | 'done'
const currentResponse = ref('')
const messagesContainer = ref<HTMLElement | null>(null)
const showScrollBtn = ref(false)
const isAtBottom = ref(true)

const statusText = {
  thinking: '贾维斯正在思考...',
  typing: '贾维斯正在输入...',
  done: ''
}

function handleScroll() {
  if (!messagesContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer.value
  const threshold = 100
  isAtBottom.value = scrollHeight - scrollTop - clientHeight < threshold
  showScrollBtn.value = !isAtBottom.value
}

function scrollToBottom(smooth = true) {
  if (!messagesContainer.value) return
  messagesContainer.value.scrollTo({
    top: messagesContainer.value.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto'
  })
}

async function handleSend() {
  const text = inputValue.value.trim()
  if (!text || isLoading.value) return

  inputValue.value = ''
  const userMsg = chatStore.addMessage('user', text)
  if (!userMsg) {
    // user_name not set, prompt to configure
    alert('请先在设置中配置用户名')
    return
  }

  isLoading.value = true
  thinkingStatus.value = 'thinking'
  currentResponse.value = ''

  try {
    // Add empty assistant message that we'll update
    chatStore.addMessage('assistant', '')
    const msgIndex = chatStore.messages.length - 1

    // Use streaming API with current conversation context
    const messagesToSend = chatStore.messages.map(m => ({
      role: m.role,
      content: m.content
    }))

    await api.chatStream(
      {
        message: text,
        stream: true,
        conversation_id: chatStore.currentConversationId || undefined,
        user_id: settingsStore.settings.user_name || undefined,
        force_refresh_models: false,
        model: settingsStore.settings.ai_default_model,
        messages: messagesToSend
      },
      (token: string) => {
        // First token means we started typing
        if (thinkingStatus.value === 'thinking') {
          thinkingStatus.value = 'typing'
        }
        currentResponse.value += token
        // Update the last message with streaming content
        if (chatStore.messages[msgIndex]) {
          chatStore.messages[msgIndex].content = currentResponse.value
        }
        // Auto-scroll during streaming if user is at bottom
        if (isAtBottom.value) {
          nextTick(() => scrollToBottom(false))
        }
      },
      () => {
        // Done
        isLoading.value = false
        thinkingStatus.value = 'done'
        // Final scroll to bottom
        nextTick(() => scrollToBottom(false))
      },
      (status: string) => {
        // Handle status updates from server
        if (status === 'thinking') {
          thinkingStatus.value = 'thinking'
        } else if (status.startsWith('tool_call:')) {
          // Display tool call in progress
          const parts = status.split(':')
          const tool = parts[1]
          const action = parts[2]
          // Add a system message showing tool call
          chatStore.addMessage('system', `🔧 正在执行工具: ${tool}.${action}`)
        } else if (status.startsWith('tool_result:')) {
          // Display tool result
          const parts = status.split(':')
          const tool = parts[1]
          const action = parts[2]
          const resultStatus = parts[3]
          const icon = resultStatus === 'success' ? '✅' : '❌'
          chatStore.addMessage('system', `${icon} 工具完成: ${tool}.${action}`)
        }
      }
    )
  } catch (e) {
    chatStore.addMessage('assistant', `抱歉，发生错误：${(e as Error).message}`)
    isLoading.value = false
    thinkingStatus.value = 'done'
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
      if (isAtBottom.value) {
        scrollToBottom(false)
      }
    })
  }
)

onMounted(() => {
  scrollToBottom(false)
})
</script>

<template>
  <div class="flex flex-col h-full relative cyber-grid">
    <div
      ref="messagesContainer"
      class="chat-messages flex-1 overflow-y-auto p-6 space-y-4 relative"
      @scroll="handleScroll"
    >
      <div v-if="chatStore.messages.length === 0" class="flex items-center justify-center h-full">
        <div class="text-center text-muted-foreground">
          <p class="text-lg mb-2 text-glow">你好，我是 JARVIS</p>
          <p class="text-sm text-muted-foreground/70">有什么可以帮你的？</p>
        </div>
      </div>

      <ChatMessage
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
      />

      <div v-if="isLoading && thinkingStatus !== 'done'" class="flex items-center gap-2">
        <div class="typing-indicator-cyber">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span class="text-sm text-primary/70">{{ statusText[thinkingStatus] }}</span>
      </div>
    </div>

    <!-- 滚动到底部按钮 -->
    <button
      v-show="showScrollBtn"
      class="absolute right-6 bottom-24 w-10 h-10 rounded-full bg-primary/20 border border-primary/50 text-primary flex items-center justify-center glow-primary opacity-80 hover:opacity-100 transition-all hover:scale-110"
      @click="scrollToBottom()"
      title="滚动到底部"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 5v14M5 12l7 7 7-7"/>
      </svg>
    </button>

    <div class="p-4 border-t border-primary/20 relative">
      <div class="absolute inset-0 bg-gradient-to-t from-background via-background/95 to-transparent pointer-events-none h-10 -top-10" />
      <div class="flex gap-3 relative z-10">
        <input
          v-model="inputValue"
          type="text"
          placeholder="输入指令..."
          class="flex-1 input-cyber rounded-full px-4 py-3 text-sm outline-none glow-border"
          :disabled="isLoading"
          @keydown="handleKeydown"
        >
        <button
          class="btn btn-cyber bg-primary/20 border border-primary/50 text-primary hover:bg-primary/30 disabled:opacity-30 disabled:cursor-not-allowed"
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
.chat-messages {
  background: linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--background) / 0.98) 100%);
}

.animate-spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>