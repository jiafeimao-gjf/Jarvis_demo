import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Conversation } from '@/types'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const isLoading = ref(false)

  const currentConversation = computed(() =>
    conversations.value.find(c => c.id === currentConversationId.value)
  )

  const messages = computed(() =>
    currentConversation.value?.messages || []
  )

  function createConversation(): Conversation {
    const conv: Conversation = {
      id: crypto.randomUUID(),
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date()
    }
    conversations.value.push(conv)
    currentConversationId.value = conv.id
    return conv
  }

  function selectConversation(id: string) {
    currentConversationId.value = id
  }

  function addMessage(role: Message['role'], content: string) {
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

    if (conv.messages.length === 1) {
      conv.title = content.slice(0, 30) + (content.length > 30 ? '...' : '')
    }

    return msg
  }

  function clearCurrentMessages() {
    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    if (conv) {
      conv.messages = []
    }
  }

  return {
    conversations,
    currentConversationId,
    currentConversation,
    messages,
    isLoading,
    createConversation,
    selectConversation,
    addMessage,
    clearCurrentMessages
  }
})