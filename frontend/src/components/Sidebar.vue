<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import { cn } from '@/lib/utils'

const chatStore = useChatStore()
const isOpen = ref(false)
const isDarkMode = ref(true)

function toggleSidebar() {
  isOpen.value = !isOpen.value
}

function handleNewChat() {
  chatStore.createConversation()
}

function selectConversation(id: string) {
  chatStore.selectConversation(id)
}

function deleteConversation(id: string, event: Event) {
  event.stopPropagation()
  chatStore.deleteConversation(id)
}

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value
  document.documentElement.classList.toggle('light')
}
</script>

<template>
  <aside
    :class="[
      'w-72 bg-secondary border-r border-border flex flex-col transition-all duration-300',
      isOpen ? 'translate-x-0' : '-translate-x-full'
    ]"
  >
    <div class="p-4 border-b border-border flex items-center justify-between">
      <h2 class="font-semibold">历史对话</h2>
      <div class="flex items-center gap-2">
        <button
          class="p-2 hover:bg-accent rounded-lg transition-colors"
          @click="toggleTheme"
          title="切换主题"
        >
          <svg v-if="isDarkMode" class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>
          </svg>
          <svg v-else class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 7a9 9 0 0 1 9 9 9 9 0 1 1-9-9c0-.46.04-1.2.1-1.36A5.38 5.38 0 0 1 14 2.36 5.38 5.38 0 0 1 12 7z"/>
          </svg>
        </button>
        <button
          class="p-2 hover:bg-accent rounded-lg transition-colors"
          @click="handleNewChat"
          title="新建对话"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2 space-y-1">
      <button
        v-for="conv in chatStore.conversations"
        :key="conv.id"
        :class="[
          'w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors group flex items-center gap-2',
          conv.id === chatStore.currentConversationId
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
        ]"
        @click="selectConversation(conv.id)"
      >
        <span class="flex-1 truncate">{{ conv.title }}</span>
        <button
          class="opacity-0 group-hover:opacity-100 p-1 hover:bg-destructive/20 rounded transition-all"
          @click="deleteConversation(conv.id, $event)"
          title="删除对话"
        >
          <svg class="w-4 h-4 text-destructive" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
          </svg>
        </button>
      </button>
    </div>

    <div class="p-4 border-t border-border">
      <div class="text-xs text-muted-foreground text-center">
        共 {{ chatStore.conversations.length }} 条对话
      </div>
    </div>
  </aside>
</template>