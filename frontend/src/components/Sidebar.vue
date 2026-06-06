<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import { useTheme } from '@/stores/theme'
import { ref, nextTick } from 'vue'
import type { Conversation } from '@/types'

const emit = defineEmits<{
  (e: 'select-conversation'): void
}>()

const chatStore = useChatStore()
const { theme, toggleTheme } = useTheme()
const isDarkMode = ref(theme.value === 'dark')

function handleNewChat() {
  chatStore.createConversation()
  emit('select-conversation')  // also jump to chat
}

function selectConversation(id: string) {
  chatStore.selectConversation(id)
  // Notify parent — App.vue uses this to close Settings if it's open,
  // so the user lands on the chat they just clicked.
  emit('select-conversation')
}

function deleteConversation(id: string, event: Event) {
  event.stopPropagation()
  chatStore.deleteConversation(id)
}

function onToggleTheme() {
  toggleTheme()
  isDarkMode.value = theme.value === 'dark'
}

// Topic inline edit
const editingId = ref<string | null>(null)
const topicDraft = ref('')
const editInput = ref<HTMLInputElement | null>(null)

function displayTitle(conv: Conversation): string {
  return conv.topic || conv.title || '新对话'
}

function startEdit(conv: Conversation, event: Event) {
  event.stopPropagation()
  editingId.value = conv.id
  topicDraft.value = conv.topic || ''
  nextTick(() => {
    editInput.value?.focus()
    editInput.value?.select()
  })
}

function commitEdit() {
  if (!editingId.value) return
  const conv = chatStore.conversations.find(c => c.id === editingId.value)
  const newTopic = topicDraft.value.trim()
  if (conv && newTopic) {
    chatStore.updateTopic(conv.id, newTopic)
  }
  cancelEdit()
}

function cancelEdit() {
  editingId.value = null
  topicDraft.value = ''
}

function onEditKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitEdit()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    cancelEdit()
  }
}
</script>

<template>
  <aside class="w-72 scifi-panel flex flex-col shrink-0 h-[calc(100vh-3.5rem)]">
    <div class="absolute inset-0 cyber-grid opacity-30 pointer-events-none" />

    <div class="p-4 border-b border-primary/20 flex items-center justify-between relative z-10">
      <h2 class="font-semibold tracking-wide text-primary/80">HISTORY</h2>
      <div class="flex items-center gap-2">
        <button
          class="p-2 hover:bg-primary/10 rounded-lg transition-all btn-cyber"
          @click="onToggleTheme"
          title="切换主题"
        >
          <svg v-if="isDarkMode" class="w-4 h-4 text-primary" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>
          </svg>
          <svg v-else class="w-4 h-4 text-primary" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 7a9 9 0 0 1 9 9 9 9 0 1 1-9-9c0-.46.04-1.2.1-1.36A5.38 5.38 0 0 1 14 2.36 5.38 5.38 0 0 1 12 7z"/>
          </svg>
        </button>
        <button
          class="p-2 hover:bg-primary/10 rounded-lg transition-all btn-cyber"
          @click="handleNewChat"
          title="新建对话"
        >
          <svg class="w-4 h-4 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2 space-y-1 relative z-10">
      <div
        v-for="conv in chatStore.conversations"
        :key="conv.id"
        :class="[
          'w-full px-3 py-2 rounded text-sm border flex items-center gap-2 group transition-all',
          conv.id === chatStore.currentConversationId
            ? 'bg-primary/10 border-primary/30 text-primary'
            : 'border-transparent hover:bg-primary/5 hover:border-primary/20 hover:text-foreground'
        ]"
      >
        <!-- Display mode: click selects, pencil edits -->
        <template v-if="editingId !== conv.id">
          <button
            class="flex-1 text-left truncate text-xs"
            @click="selectConversation(conv.id)"
          >
            {{ displayTitle(conv) }}
          </button>
          <button
            class="opacity-0 group-hover:opacity-100 p-1 hover:bg-primary/20 rounded transition-all shrink-0"
            @click="startEdit(conv, $event)"
            title="编辑主题"
          >
            <svg class="w-3 h-3 text-primary/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button
            class="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded transition-all shrink-0"
            @click="deleteConversation(conv.id, $event)"
            title="删除对话"
          >
            <svg class="w-3 h-3 text-red-400/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
            </svg>
          </button>
        </template>
        <!-- Edit mode -->
        <template v-else>
          <input
            ref="editInput"
            v-model="topicDraft"
            class="flex-1 bg-background/50 border border-primary/40 rounded px-2 py-1 text-xs outline-none focus:border-primary"
            maxlength="60"
            @keydown="onEditKeydown"
            @blur="commitEdit"
            @click.stop
          />
        </template>
      </div>
    </div>

    <div class="p-3 border-t border-primary/20 relative z-10">
      <div class="text-[10px] text-primary/40 text-center tracking-widest uppercase">
        {{ chatStore.conversations.length }} CONVERSATIONS
      </div>
    </div>
  </aside>
</template>
