import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Conversation } from '@/types'
import { useSettingsStore } from '@/stores/settings'

// sessionStorage cache: instant topic display on page reload
// Avoids the "未命名对话" flash before loadFromBackend completes.
const TOPIC_CACHE_KEY = 'jarvis_topic_cache_v1'

function loadTopicCache(): Record<string, string> {
  try {
    const raw = sessionStorage.getItem(TOPIC_CACHE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return (parsed && typeof parsed === 'object') ? parsed : {}
  } catch {
    return {}
  }
}

function saveTopicCache(cache: Record<string, string>) {
  try {
    sessionStorage.setItem(TOPIC_CACHE_KEY, JSON.stringify(cache))
  } catch {
    // Quota exceeded or storage disabled — silently ignore
  }
}

export const useChatStore = defineStore('chat', () => {
  const settingsStore = useSettingsStore()
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const isLoading = ref(false)
  const isSyncing = ref(false)

  // Reactive copy of sessionStorage topic cache — updated whenever topics change
  const topicCache = ref<Record<string, string>>(loadTopicCache())

  function rememberTopic(conversationId: string, topic: string | undefined) {
    if (topic) {
      topicCache.value[conversationId] = topic
    } else {
      delete topicCache.value[conversationId]
    }
    saveTopicCache(topicCache.value)
  }

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
        const cache = topicCache.value

        conversations.value = backendConvs.map((conv: any) => {
          // Prefer backend topic; fall back to sessionStorage cache for instant display
          const topic = conv.topic || cache[conv.conversation_id] || undefined
          // If we served from cache but backend has a topic now, sync back to cache
          if (conv.topic && cache[conv.conversation_id] !== conv.topic) {
            rememberTopic(conv.conversation_id, conv.topic)
          }
          return {
            id: conv.conversation_id,
            title: conv.title || `对话 ${conv.message_count} 条消息`,
            topic,
            messages: [],
            createdAt: new Date(conv.created_at),
            updatedAt: new Date(conv.updated_at)
          }
        })
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

  // Topic management — optimistic local update + debounced PUT
  let topicUpdateTimeout: ReturnType<typeof setTimeout> | null = null
  function updateTopic(conversationId: string, topic: string) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    const normalized = (topic || '').trim().slice(0, 60)
    if (!normalized) return  // ignore empty

    // Optimistic local update + sessionStorage cache
    const previous = conv.topic
    conv.topic = normalized
    rememberTopic(conversationId, normalized)

    // Debounced PUT
    if (topicUpdateTimeout) clearTimeout(topicUpdateTimeout)
    topicUpdateTimeout = setTimeout(async () => {
      try {
        const res = await fetch(`/api/memory/conversation/${conversationId}/topic`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic: normalized })
        })
        if (!res.ok) {
          conv.topic = previous  // revert
          if (previous) rememberTopic(conversationId, previous)
          else rememberTopic(conversationId, undefined as any)
          console.error(`Update topic failed: ${res.status}`)
        }
      } catch (e) {
        conv.topic = previous
        if (previous) rememberTopic(conversationId, previous)
        else rememberTopic(conversationId, undefined as any)
        console.error('Update topic error:', e)
      }
    }, 600)
  }

  // Apply topic update from SSE — local-only setter (backend already persisted)
  function applyTopicUpdate(conversationId: string, topic: string) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    // Don't overwrite if user has already edited it manually
    // (race: SSE may arrive after manual edit)
    if (conv.topic && conv.topic !== topic && conv.topic.length > 0) {
      return  // user has a real topic; keep it
    }
    const cleaned = (topic || '').trim().slice(0, 60)
    conv.topic = cleaned
    rememberTopic(conversationId, cleaned)
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
    loadFromBackend,
    updateTopic,
    applyTopicUpdate,
  }
})