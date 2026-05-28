<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import { ref } from 'vue'

const chatStore = useChatStore()
const isDarkMode = ref(true)

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
    class="w-72 scifi-panel flex flex-col relative"
    style="top: 56px; height: calc(100vh - 56px);"
  >
    <div class="absolute inset-0 cyber-grid opacity-30 pointer-events-none" />

    <div class="p-4 border-b border-primary/20 flex items-center justify-between relative z-10">
      <h2 class="font-semibold tracking-wide text-primary/80">HISTORY</h2>
      <div class="flex items-center gap-2">
        <button
          class="p-2 hover:bg-primary/10 rounded-lg transition-all btn-cyber"
          @click="toggleTheme"
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
      <button
        v-for="conv in chatStore.conversations"
        :key="conv.id"
        :class="[
          'w-full text-left px-3 py-2 rounded text-sm truncate transition-all group flex items-center gap-2 border',
          conv.id === chatStore.currentConversationId
            ? 'bg-primary/10 border-primary/30 text-primary'
            : 'border-transparent hover:bg-primary/5 hover:border-primary/20 hover:text-foreground'
        ]"
        @click="selectConversation(conv.id)"
      >
        <span class="flex-1 truncate text-xs">{{ conv.title }}</span>
        <button
          class="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded transition-all"
          @click="deleteConversation(conv.id, $event)"
          title="删除对话"
        >
          <svg class="w-3 h-3 text-red-400/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
          </svg>
        </button>
      </button>
    </div>

    <div class="p-3 border-t border-primary/20 relative z-10">
      <div class="text-[10px] text-primary/40 text-center tracking-widest uppercase">
        {{ chatStore.conversations.length }} CONVERSATIONS
      </div>
    </div>
  </aside>
</template>