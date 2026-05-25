import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { Message, Conversation } from '@/types'
import { useApi } from '@/composables/useApi'

const STORAGE_KEY = 'jarvis_conversations'
const CURRENT_KEY = 'jarvis_current_conversation'

export const useChatStore = defineStore('chat', () => {
  const api = useApi()
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

  // Initialize from localStorage
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored, (key, value) => {
          if (key === 'createdAt' || key === 'updatedAt' || key === 'timestamp') {
            return new Date(value)
          }
          return value
        })
        conversations.value = parsed.conversations || []
        currentConversationId.value = parsed.currentId || null
      }
    } catch (e) {
      console.error('Failed to load from storage:', e)
    }
  }

  // Save to localStorage
  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        conversations: conversations.value,
        currentId: currentConversationId.value
      }))
    } catch (e) {
      console.error('Failed to save to storage:', e)
    }
  }

  // Watch for changes and persist
  watch([conversations, currentConversationId], () => {
    saveToStorage()
  }, { deep: true })

  // Load conversations from backend
  async function loadFromBackend() {
    if (isSyncing.value) return
    isSyncing.value = true

    try {
      const response = await fetch('/api/memory/conversations?limit=100')
      if (response.ok) {
        const data = await response.json()
        // Merge with local storage, preferring local newer versions
        const backendConvs = data.conversations || []

        for (const backendConv of backendConvs) {
          const localConv = conversations.value.find(
            c => c.id === backendConv.conversation_id
          )
          if (!localConv) {
            // New from backend
            conversations.value.push({
              id: backendConv.conversation_id,
              title: `对话 ${backendConv.message_count} 条消息`,
              messages: [],
              createdAt: new Date(backendConv.created_at),
              updatedAt: new Date(backendConv.updated_at)
            })
          }
        }
      }
    } catch (e) {
      console.error('Failed to load from backend:', e)
    } finally {
      isSyncing.value = false
    }
  }

  // Sync current conversation to backend
  async function syncToBackend(conversation: Conversation) {
    if (!conversation || !conversation.id) return

    try {
      await fetch(`/api/memory/conversation/${conversation.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: '',
          messages: conversation.messages.map(m => ({
            role: m.role,
            content: m.content
          })),
          context: {}
        })
      })
    } catch (e) {
      console.error('Failed to sync to backend:', e)
    }
  }

  // Create new conversation
  function createConversation(): Conversation {
    const conv: Conversation = {
      id: crypto.randomUUID(),
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date()
    }
    conversations.value.unshift(conv) // Add to beginning
    currentConversationId.value = conv.id
    return conv
  }

  // Select conversation
  let previousConversationId: string | null = null
  function selectConversation(id: string) {
    // Sync previous conversation before switching
    if (previousConversationId && previousConversationId !== id) {
      const prevConv = conversations.value.find(c => c.id === previousConversationId)
      if (prevConv) {
        syncToBackend(prevConv)
      }
    }
    previousConversationId = currentConversationId.value
    currentConversationId.value = id
  }

  // Add message
  function addMessage(role: Message['role'], content: string): Message | undefined {
    if (!currentConversationId.value) {
      createConversation()
    }

    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    if (!conv) return

    const msg: Message = {
      id: crypto.randomUUID(),
      role,
      content,
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
      // Delete from backend
      fetch(`/api/memory/conversation/${id}`, { method: 'DELETE' }).catch(console.error)
    }
  }

  // Debounced sync helper
  let syncTimeout: ReturnType<typeof setTimeout> | null = null
  function debouncedSync(conv: Conversation) {
    if (syncTimeout) clearTimeout(syncTimeout)
    syncTimeout = setTimeout(() => syncToBackend(conv), 2000)
  }

  // Initialize
  loadFromStorage()
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