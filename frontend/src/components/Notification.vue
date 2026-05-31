<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useNotificationStore } from '@/stores/notification'
import { formatTime } from '@/lib/utils'

const store = useNotificationStore()
const isOpen = ref(false)
const activeTab = ref<'all' | 'errors'>('all')

const filteredNotifications = computed(() => {
  if (activeTab.value === 'errors') {
    return store.notifications.filter(n => n.level === 'error' || n.level === 'critical')
  }
  return store.notifications
})

const levelColors: Record<string, string> = {
  debug: 'bg-gray-500',
  info: 'bg-blue-500',
  warning: 'bg-yellow-500',
  error: 'bg-red-500',
  critical: 'bg-red-700'
}

const levelIcons: Record<string, string> = {
  debug: 'ℹ️',
  info: 'ℹ️',
  warning: '⚠️',
  error: '❌',
  critical: '🚨'
}

function togglePanel() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    store.markRead()
  }
}

onMounted(() => {
  store.connect()
  store.fetchHistory()
})

onUnmounted(() => {
  store.disconnect()
})
</script>

<template>
  <!-- 通知按钮 -->
  <button
    class="relative p-2 hover:bg-accent rounded-lg transition-colors"
    @click="togglePanel"
    title="通知"
  >
    <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
    <span
      v-if="store.hasUnread"
      class="absolute top-0 right-0 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center"
    >
      {{ store.unreadCount > 9 ? '9+' : store.unreadCount }}
    </span>
  </button>

  <!-- 通知面板 -->
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 z-50"
      @click="isOpen = false"
    >
      <div
        class="absolute top-16 right-4 w-80 md:w-96 max-h-[70vh] bg-background border border-border rounded-lg shadow-xl overflow-hidden flex flex-col"
        @click.stop
      >
        <!-- 头部 -->
        <div class="p-4 border-b border-border flex items-center justify-between">
          <h2 class="text-lg font-semibold">通知</h2>
          <div class="flex gap-2">
            <button
              class="px-3 py-1 text-xs rounded-full hover:bg-accent"
              :class="activeTab === 'all' ? 'bg-primary text-primary-foreground' : ''"
              @click="activeTab = 'all'"
            >
              全部
            </button>
            <button
              class="px-3 py-1 text-xs rounded-full hover:bg-accent"
              :class="activeTab === 'errors' ? 'bg-primary text-primary-foreground' : ''"
              @click="activeTab = 'errors'"
            >
              错误
            </button>
            <button
              class="ml-4 text-xs text-muted-foreground hover:text-foreground"
              @click="store.clear"
            >
              清空
            </button>
            <button
              class="ml-2 text-xs text-muted-foreground hover:text-foreground"
              @click="isOpen = false"
            >
              关闭
            </button>
          </div>
        </div>

        <!-- 连接状态 -->
        <div class="px-4 py-2 text-xs text-muted-foreground flex items-center gap-2">
          <span
            :class="['w-2 h-2 rounded-full', store.isConnected ? 'bg-green-500' : 'bg-red-500']"
          />
          {{ store.isConnected ? '实时连接' : '离线' }}
        </div>

        <!-- 通知列表 -->
        <div class="flex-1 overflow-y-auto">
          <div v-if="filteredNotifications.length === 0" class="p-8 text-center text-muted-foreground">
            暂无通知
          </div>
          <div v-else class="divide-y divide-border">
            <div
              v-for="n in filteredNotifications"
              :key="n.id"
              class="p-4 hover:bg-accent/50 transition-colors"
            >
              <div class="flex items-start gap-3">
                <span class="text-lg">{{ levelIcons[n.level] || 'ℹ️' }}</span>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span
                      :class="['w-2 h-2 rounded-full', levelColors[n.level]]"
                    />
                    <span class="font-medium text-sm">{{ n.title }}</span>
                    <span class="text-xs text-muted-foreground ml-auto">
                      {{ formatTime(n.timestamp) }}
                    </span>
                  </div>
                  <p class="text-sm text-muted-foreground mt-1 break-words">
                    {{ n.message }}
                  </p>
                  <p v-if="n.metadata?.file" class="text-xs text-muted-foreground mt-1">
                    {{ n.metadata.file }}:{{ n.metadata.line }}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>