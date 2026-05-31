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
const currentThinking = ref('')
const showThinking = ref(false)
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
  currentThinking.value = ''
  showThinking.value = false

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
          const parts = status.split(':')
          chatStore.addMessage('system', `🔧 正在执行工具: ${parts[1]}.${parts[2]}`)
        } else if (status.startsWith('tool_result:')) {
          const parts = status.split(':')
          const icon = parts[3] === 'success' ? '✅' : '❌'
          chatStore.addMessage('system', `${icon} 工具完成: ${parts[1]}.${parts[2]}`)
        }
      },
      (chunk: string) => {
        // Thinking stream
        if (!showThinking.value) showThinking.value = true
        currentThinking.value += chunk
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

async function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return

  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (!file) continue

      // Convert to base64
      const reader = new FileReader()
      reader.onload = async () => {
        const dataUrl = reader.result as string
        const base64 = dataUrl.split(',')[1]
        if (!base64) return

        // Add placeholder
        const placeholderIdx = chatStore.messages.length
        chatStore.addMessage('assistant', '📷 正在分析图片...', dataUrl)

        try {
          const result = await api.analyzeCameraFrame(base64)
          if (result.analysis) {
            // Replace placeholder with analysis result
            if (chatStore.messages[placeholderIdx]) {
              chatStore.messages[placeholderIdx].content = `📷 [图片分析]\n\n${result.analysis}`
            }
          } else {
            if (chatStore.messages[placeholderIdx]) {
              chatStore.messages[placeholderIdx].content = '📷 图片分析失败'
            }
          }
        } catch {
          if (chatStore.messages[placeholderIdx]) {
            chatStore.messages[placeholderIdx].content = '📷 图片分析失败'
          }
        }
      }
      reader.readAsDataURL(file)
      return
    }
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

      <!-- Thinking 折叠显示 -->
      <div v-if="showThinking && (currentThinking || isLoading)" class="px-4 py-2">
        <button
          class="flex items-center gap-2 text-xs text-primary/50 hover:text-primary/70 transition-colors mb-1"
          @click="showThinking = !showThinking"
        >
          <span>{{ showThinking ? '▼' : '▶' }} 思考过程</span>
          <span v-if="isLoading && currentThinking" class="text-primary/30">...</span>
        </button>
        <div v-if="showThinking && currentThinking" class="text-xs text-primary/40 bg-black/20 rounded-lg p-3 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">
          {{ currentThinking }}
        </div>
      </div>

      <div v-if="isLoading && thinkingStatus !== 'done'" class="flex items-center gap-2">
        <div class="typing-indicator-cyber">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span class="text-sm text-primary/70">{{ statusText[thinkingStatus as keyof typeof statusText] }}</span>
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
        <textarea
          v-model="inputValue"
          placeholder="输入指令回车发送，Shift+Enter 换行，可粘贴图片"
          class="flex-1 input-cyber rounded-2xl px-4 py-3 text-sm outline-none glow-border resize-none"
          :disabled="isLoading"
          rows="1"
          @keydown="handleKeydown"
          @paste="handlePaste"
        ></textarea>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-messages {
  background: linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--background) / 0.98) 100%);
}
</style>