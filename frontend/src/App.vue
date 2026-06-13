<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useProvidersStore } from '@/stores/providers'
import { useApi } from '@/composables/useApi'
import Header from '@/components/Header.vue'
import Sidebar from '@/components/Sidebar.vue'
import ChatWindow from '@/components/ChatWindow.vue'
import HardwareControls from '@/components/HardwareControls.vue'
import CameraPreview from '@/components/CameraPreview.vue'
import Settings from '@/components/Settings.vue'

const hardware = useHardwareStore()
const providersStore = useProvidersStore()
const api = useApi()
const settingsOpen = ref(false)

let statusInterval: ReturnType<typeof setInterval>

onMounted(async () => {
  // Load provider instances before status check
  await providersStore.loadFromBackend()
  await providersStore.loadActive()

  // Initial status check
  try {
    const status = await api.getStatus()
    if (status) {
      hardware.updateSystemStatus({
        server: status.status === 'online',
        ollama: (status.systems as any)?.['chat_engine']?.ollama_connected ?? false
      })
    }
  } catch (e) {
    console.error('Failed to get status:', e)
  }

  // Periodic status check
  statusInterval = setInterval(async () => {
    try {
      const status = await api.getStatus()
      if (status) {
        hardware.updateSystemStatus({
          server: status.status === 'online',
          ollama: (status.systems as any)?.['chat_engine']?.ollama_connected ?? false
        })
      }
    } catch {
      hardware.updateSystemStatus({ server: false })
    }
  }, 5000)
})

onUnmounted(() => {
  clearInterval(statusInterval)
})

function openSettings() {
  settingsOpen.value = true
}

function closeSettings() {
  settingsOpen.value = false
}

// Fired by Sidebar when the user picks/creates a conversation. Closes the
// Settings overlay so the user immediately lands on the chat they picked.
function onSidebarSelectConversation() {
  if (settingsOpen.value) {
    settingsOpen.value = false
  }
}
</script>

<template>
  <div class="h-screen flex flex-col bg-background">
    <Header @open-settings="openSettings" />

    <div class="flex flex-1 overflow-hidden">
      <Sidebar @select-conversation="onSidebarSelectConversation" />
      <main class="flex-1 flex flex-col">
        <Settings v-if="settingsOpen" @close="closeSettings" />
        <ChatWindow v-else />
      </main>
    </div>

    <HardwareControls />
    <CameraPreview />
  </div>
</template>