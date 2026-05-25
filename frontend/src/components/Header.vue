<script setup lang="ts">
import { ref } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'

const hardware = useHardwareStore()
const speech = useSpeechRecognition()
const sidebarOpen = ref(false)

const emit = defineEmits<{
  (e: 'open-settings'): void
}>()

function toggleMic() {
  speech.toggle()
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
  document.body.dataset.sidebarOpen = sidebarOpen.value ? 'true' : 'false'
}

function openSettings() {
  emit('open-settings')
}
</script>

<template>
  <header class="h-14 bg-secondary border-b border-border flex items-center justify-between px-6">
    <div class="flex items-center gap-3">
      <button
        class="p-2 hover:bg-accent rounded-lg transition-colors"
        @click="toggleSidebar"
        title="切换侧边栏"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12h18M3 6h18M3 18h18"/>
        </svg>
      </button>
      <div class="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
        <span class="text-lg font-bold text-primary-foreground">J</span>
      </div>
      <h1 class="text-lg font-semibold">贾维斯</h1>
    </div>

    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.system.server ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        服务器
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.system.ollama ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        Ollama
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.hardware.microphone ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        麦克风
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.hardware.camera ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        摄像头
      </div>

      <button
        class="p-2 hover:bg-accent rounded-lg transition-colors"
        @click="openSettings"
        title="设置"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>
  </header>
</template>