import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Conversation } from '@/types'
import { useSettingsStore } from '@/stores/settings'

export const useChatStore = defineStore('chat', () => {
  const settingsStore = useSettingsStore()
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const isLoading = ref(false)
  const isSyncing = ref(false)

  // Computed
  const currentConversation = computed(() =>
    conversations.value.find(c => c.id === currentConversationId.value)
  )

  const messages = computed(() =>
    currentConversation.value?.messages || []
  )

  // Load conversations from backend
  async function loadFromBackend() {
    if (isSyncing.value) return
    isSyncing.value = true

    try {
      const response = await fetch('/api/memory/conversations?limit=100')
      if (response.ok) {
        const data = await response.json()
        const backendConvs = data.conversations || []

        conversations.value = backendConvs.map((conv: any) => ({
          id: conv.conversation_id,
          title: conv.title || `对话 ${conv.message_count} 条消息`,
          messages: [],
          createdAt: new Date(conv.created_at),
          updatedAt: new Date(conv.updated_at)
        }))
      }
    } catch (e) {
      console.error('Failed to load from backend:', e)
    } finally {
      isSyncing.value = false
    }
  }

  // Sync current conversation to backend with retry
  async function syncToBackend(conversation: Conversation, retries = 3): Promise<boolean> {
    if (!conversation || !conversation.id) return false

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const response = await fetch(`/api/memory/conversation/${conversation.id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_id: conversation.userId || '',
            messages: conversation.messages.map(m => ({
              role: m.role,
              content: m.content,
              image: m.image || undefined,
            })),
            context: conversation.context || {}
          })
        })

        if (response.ok) {
          return true
        }
        console.error(`Sync attempt ${attempt} failed: ${response.status}`)
      } catch (e) {
        console.error(`Sync attempt ${attempt} error:`, e)
      }

      if (attempt < retries) {
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt))
      }
    }
    return false
  }

  // Create new conversation
  function createConversation(): Conversation | null {
    const userName = settingsStore.settings.user_name
    if (!userName) {
      // Prompt user to set user name in settings
      return null
    }

    const conv: Conversation = {
      id: crypto.randomUUID(),
      userId: userName,
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date()
    }
    conversations.value.unshift(conv)
    currentConversationId.value = conv.id
    return conv
  }

  // Select conversation
  let previousConversationId: string | null = null
  async function selectConversation(id: string) {
    // Sync previous conversation before switching
    if (previousConversationId && previousConversationId !== id) {
      const prevConv = conversations.value.find(c => c.id === previousConversationId)
      if (prevConv) {
        await syncToBackend(prevConv)
      }
    }

    // Load full messages for selected conversation if needed
    const conv = conversations.value.find(c => c.id === id)
    if (conv && conv.messages.length === 0) {
      try {
        const response = await fetch(`/api/memory/conversation/${id}`)
        if (response.ok) {
          const data = await response.json()
          if (data.messages) {
            conv.messages = data.messages.map((m: any) => ({
              id: crypto.randomUUID(),
              role: m.role,
              content: m.content,
              image: m.image || undefined,
              timestamp: new Date(m.timestamp || Date.now())
            }))
          }
        }
      } catch (e) {
        console.error('Failed to load conversation messages:', e)
      }
    }

    previousConversationId = currentConversationId.value
    currentConversationId.value = id
  }

  // Add message
  function addMessage(role: Message['role'], content: string, image?: string): Message | undefined {
    if (!currentConversationId.value) {
      const conv = createConversation()
      if (!conv) return  // user_name not set
    }

    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    if (!conv) return

    const msg: Message = {
      id: crypto.randomUUID(),
      role,
      content,
      image,
      timestamp: new Date()
    }
    conv.messages.push(msg)
    conv.updatedAt = new Date()

    // Update title from first user message
    if (conv.messages.length === 1 && role === 'user') {
      conv.title = content.slice(0, 30) + (content.length > 30 ? '...' : '')
    }

    // Debounced sync to backend
    debouncedSync(conv)

    return msg
  }

  // Clear current messages
  function clearCurrentMessages() {
    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    if (conv) {
      conv.messages = []
      debouncedSync(conv)
    }
  }

  // Delete conversation
  function deleteConversation(id: string) {
    const index = conversations.value.findIndex(c => c.id === id)
    if (index !== -1) {
      conversations.value.splice(index, 1)
      if (currentConversationId.value === id) {
        currentConversationId.value = conversations.value[0]?.id || null
      }
      // Delete from backend (fire and forget)
      fetch(`/api/memory/conversation/${id}`, { method: 'DELETE' }).catch(() => {})
    }
  }

  // Debounced sync helper
  let syncTimeout: ReturnType<typeof setTimeout> | null = null
  function debouncedSync(conv: Conversation) {
    if (syncTimeout) clearTimeout(syncTimeout)
    syncTimeout = setTimeout(() => syncToBackend(conv), 2000)
  }

  // Initialize
  loadFromBackend()

  return {
    conversations,
    currentConversationId,
    currentConversation,
    messages,
    isLoading,
    isSyncing,
    createConversation,
    selectConversation,
    addMessage,
    clearCurrentMessages,
    deleteConversation,
    syncToBackend,
    loadFromBackend
  }
})