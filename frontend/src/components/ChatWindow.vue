<script setup lang="ts">
import { ref, watch, nextTick, onMounted, computed } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useProvidersStore } from '@/stores/providers'
import { useApi } from '@/composables/useApi'
import ChatMessage from './ChatMessage.vue'
import SubagentSessionPanel from './SubagentSessionPanel.vue'

const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const providersStore = useProvidersStore()
const api = useApi()
const inputValue = ref('')
const isLoading = ref(false)
let abortController: AbortController | null = null
const thinkingStatus = ref('thinking') // 'thinking' | 'typing' | 'done'
const currentResponse = ref('')
const currentThinking = ref('')
const showThinking = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)
const showScrollBtn = ref(false)
const isAtBottom = ref(true)

// v3: subagent session 抽屉
const activeSubSessionId = ref<string | null>(null)
const activeBatchIds = ref<string[]>([])

function openSubagentSession(subSessionId: string) {
  activeSubSessionId.value = subSessionId
  activeBatchIds.value = []
}

function openSubagentBatch(subSessionIds: string[], activeIndex: number) {
  activeBatchIds.value = subSessionIds
  activeSubSessionId.value = subSessionIds[activeIndex] ?? null
}

function closeSubagentPanel() {
  activeSubSessionId.value = null
  activeBatchIds.value = []
}

// ESC 关闭抽屉
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && (activeSubSessionId.value || activeBatchIds.value.length)) {
    closeSubagentPanel()
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))

// Topic header — click-to-edit
const isEditingTopic = ref(false)
const topicDraft = ref('')
const topicInput = ref<HTMLInputElement | null>(null)
const topicDisplay = computed(() =>
  chatStore.currentConversation?.topic?.trim() || '未命名对话'
)

function startTopicEdit() {
  if (!chatStore.currentConversation) return
  topicDraft.value = chatStore.currentConversation.topic || ''
  isEditingTopic.value = true
  nextTick(() => {
    topicInput.value?.focus()
    topicInput.value?.select()
  })
}

function commitTopicEdit() {
  if (!chatStore.currentConversation) {
    isEditingTopic.value = false
    return
  }
  const newTopic = topicDraft.value.trim()
  if (newTopic) {
    chatStore.updateTopic(chatStore.currentConversation.id, newTopic)
  }
  isEditingTopic.value = false
}

function cancelTopicEdit() {
  isEditingTopic.value = false
  topicDraft.value = ''
}

function onTopicKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitTopicEdit()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    cancelTopicEdit()
  }
}

// Reset edit state when switching conversations
watch(
  () => chatStore.currentConversationId,
  () => {
    isEditingTopic.value = false
    topicDraft.value = ''
  }
)

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
  abortController = new AbortController()
  let msgIndex = -1

  try {
    // Add empty assistant message that we'll update
    chatStore.addMessage('assistant', '')
    msgIndex = chatStore.messages.length - 1

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
        model: providersStore.activeInstance?.default_model || settingsStore.settings.ai_default_model,
        provider_id: providersStore.activeProviderId || undefined,
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
        // Done — save thinking to the assistant message
        if (currentThinking.value && chatStore.messages[msgIndex]) {
          chatStore.messages[msgIndex].thinking = currentThinking.value
        }
        isLoading.value = false
        thinkingStatus.value = 'done'
        showThinking.value = false
        nextTick(() => scrollToBottom(false))
      },
      (status: string | Record<string, unknown>) => {
        // Handle status updates from server
        if (typeof status === 'string') {
          if (status === 'thinking') {
            thinkingStatus.value = 'thinking'
          } else if (status.startsWith('tool_iter_')) {
            // Tool iteration progress — ignore string, handled by tool events
          } else if (status === 'tool_detected') {
            // Tool detected during streaming — keep thinking indicator
          }
        } else {
          // Structured tool event from SSE
          if (status.type === 'tool_call') {
            const tool = status.tool as string
            const action = status.action as string
            const params = status.params as Record<string, unknown> || {}
            chatStore.addMessage('tool', JSON.stringify({
              tool, action, params
            }))
          } else if (status.type === 'tool_result') {
            const tool = status.tool as string
            const action = status.action as string
            const resultStatus = (status.status as string) || 'success'
            const result = status.result as Record<string, unknown> || {}
            // Format result content for display
            const detail = result.stdout || result.content || result.message
              || result.stderr || JSON.stringify(result)
            const prefix = resultStatus === 'success' ? '[工具结果]' : '[工具错误]'
            chatStore.addMessage('tool_result', `${prefix} ${tool}.${action}: ${detail}`)
          }
        }
      },
      (chunk: string) => {
        // Thinking stream — write to current message for inline display
        if (!showThinking.value) showThinking.value = true
        currentThinking.value += chunk
        if (chatStore.messages[msgIndex]) {
          chatStore.messages[msgIndex].thinking = currentThinking.value
        }
      },
      abortController.signal,
      (topic: string) => {
        // Topic auto-generated by backend — apply to current conversation
        if (chatStore.currentConversationId) {
          chatStore.applyTopicUpdate(chatStore.currentConversationId, topic)
        }
      }
    )
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      // User stopped — add placeholder for what we got so far
      if (currentResponse.value && chatStore.messages[msgIndex]) {
        chatStore.messages[msgIndex].content = currentResponse.value + '\n\n*[已停止]*'
      }
    } else {
      chatStore.addMessage('assistant', `抱歉，发生错误：${(e as Error).message}`)
    }
    isLoading.value = false
    thinkingStatus.value = 'done'
    abortController = null
  }
}

function handleStop() {
  if (abortController) {
    abortController.abort()
    abortController = null
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
    <!-- Topic header — display or click-to-edit -->
    <div class="topic-header border-b border-primary/10 px-6 py-3 flex items-center gap-2 bg-background/30 relative z-10">
      <span class="text-[10px] uppercase tracking-widest text-muted-foreground/60">主题</span>
      <template v-if="!isEditingTopic">
        <button
          class="flex-1 text-left text-sm font-medium text-foreground hover:text-primary transition-colors truncate"
          :title="topicDisplay"
          @click="startTopicEdit"
        >
          {{ topicDisplay }}
        </button>
        <button
          class="p-1 hover:bg-primary/10 rounded transition-all opacity-50 hover:opacity-100 shrink-0"
          @click="startTopicEdit"
          title="编辑主题"
        >
          <svg class="w-3.5 h-3.5 text-primary/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
      </template>
      <template v-else>
        <input
          ref="topicInput"
          v-model="topicDraft"
          class="flex-1 bg-background/60 border border-primary/40 rounded px-2 py-1 text-sm outline-none focus:border-primary"
          maxlength="60"
          placeholder="输入对话主题..."
          @keydown="onTopicKeydown"
          @blur="commitTopicEdit"
        />
      </template>
    </div>

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
        @open-subagent-session="openSubagentSession"
        @open-subagent-batch="openSubagentBatch"
      />

      <div v-if="isLoading && thinkingStatus !== 'done'" class="flex items-center gap-2">
        <button
          class="px-3 py-1 text-xs rounded-full bg-red-500/20 text-red-400 border border-red-500/50 hover:bg-red-500/30 transition-colors"
          @click="handleStop"
        >停止</button>
        <div class="typing-indicator-cyber">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span class="text-sm text-foreground/60">{{ statusText[thinkingStatus as keyof typeof statusText] }}</span>
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

    <!-- v3: Subagent 完整会话抽屉 -->
    <SubagentSessionPanel
      :sub-session-id="activeSubSessionId"
      :batch-ids="activeBatchIds"
      @close="closeSubagentPanel"
    />
  </div>
</template>

<style scoped>
.chat-messages {
  background: linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--background) / 0.98) 100%);
}
</style>