import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface Notification {
  id: string
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  type: string
  title: string
  message: string
  timestamp: string
  metadata?: Record<string, unknown>
}

export const useNotificationStore = defineStore('notification', () => {
  const notifications = ref<Notification[]>([])
  const unreadCount = ref(0)
  const isConnected = ref(false)
  let ws: WebSocket | null = null
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const MAX_RECONNECT_DELAY = 30000

  const hasUnread = computed(() => unreadCount.value > 0)

  const recentNotifications = computed(() =>
    notifications.value.slice(0, 20)
  )

  function connect() {
    if (ws) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      isConnected.value = true
      reconnectAttempts = 0
      console.log('Notification WebSocket connected')
    }

    ws.onclose = () => {
      isConnected.value = false
      ws = null
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts) + Math.random() * 1000, MAX_RECONNECT_DELAY)
      reconnectAttempts++
      console.log(`WebSocket closed, reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`)
      reconnectTimer = setTimeout(connect, delay)
    }

    ws.onerror = (error) => {
      console.error('Notification WebSocket error:', error)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'notification') {
          addNotification(data.data)
        }
      } catch (e) {
        console.error('Failed to parse notification:', e)
      }
    }
  }

  function disconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    reconnectAttempts = 0
    if (ws) {
      ws.close()
      ws = null
    }
  }

  function addNotification(notification: Notification) {
    notifications.value.unshift(notification)
    unreadCount.value++

    // 限制最大数量
    if (notifications.value.length > 100) {
      notifications.value.pop()
    }
  }

  async function fetchHistory(limit = 50) {
    try {
      const res = await fetch(`/api/notifications?limit=${limit}`)
      if (res.ok) {
        const data = await res.json()
        notifications.value = data.notifications || []
        unreadCount.value = 0
      }
    } catch (e) {
      console.error('Failed to fetch notifications:', e)
    }
  }

  async function clear() {
    try {
      await fetch('/api/notifications', { method: 'DELETE' })
      notifications.value = []
      unreadCount.value = 0
    } catch (e) {
      console.error('Failed to clear notifications:', e)
    }
  }

  function markRead() {
    unreadCount.value = 0
  }

  return {
    notifications,
    unreadCount,
    isConnected,
    hasUnread,
    recentNotifications,
    connect,
    disconnect,
    addNotification,
    fetchHistory,
    clear,
    markRead
  }
})