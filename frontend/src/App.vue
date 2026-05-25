<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useApi } from '@/composables/useApi'
import Header from '@/components/Header.vue'
import Sidebar from '@/components/Sidebar.vue'
import ChatWindow from '@/components/ChatWindow.vue'
import HardwareControls from '@/components/HardwareControls.vue'
import CameraPreview from '@/components/CameraPreview.vue'

const hardware = useHardwareStore()
const api = useApi()

let statusInterval: ReturnType<typeof setInterval>

onMounted(async () => {
  // Initial status check
  try {
    const status = await api.getStatus()
    if (status) {
      hardware.updateSystemStatus({
        server: status.status === 'online',
        ollama: status.systems?.chatEngine?.ollama_connected ?? false
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
          ollama: status.systems?.chatEngine?.ollama_connected ?? false
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
</script>

<template>
  <div class="h-screen flex flex-col bg-background">
    <Header />

    <div class="flex flex-1 overflow-hidden">
      <Sidebar />
      <main class="flex-1 flex flex-col">
        <ChatWindow />
      </main>
    </div>

    <HardwareControls />
    <CameraPreview />
  </div>
</template>