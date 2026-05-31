<script setup lang="ts">
import { useHardwareStore } from '@/stores/hardware'
import { useChatStore } from '@/stores/chat'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { useApi } from '@/composables/useApi'
import { ref, onUnmounted } from 'vue'

const hardware = useHardwareStore()
const chatStore = useChatStore()
const speech = useSpeechRecognition()
const api = useApi()

const isProcessingVoice = ref(false)
const recordingSeconds = ref(0)
let recordTimer: ReturnType<typeof setInterval> | null = null

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

async function handleVoiceToggle() {
  // Recording → stop and process
  if (speech.isRecording.value) {
    // Stop timer
    if (recordTimer) { clearInterval(recordTimer); recordTimer = null }
    recordingSeconds.value = 0

    const audioBase64 = await speech.stopCapture()
    if (!audioBase64) return

    // Process
    isProcessingVoice.value = true
    try {
      const resp = await api.voice(audioBase64, chatStore.currentConversationId || undefined)
      if (resp.text) chatStore.addMessage('user', `🎤 ${resp.text}`)
      if (resp.response) {
        chatStore.addMessage('assistant', resp.response)
        speech.speak(resp.response)
      }
    } catch (e) {
      console.error('Voice failed:', e)
    } finally {
      isProcessingVoice.value = false
    }
    return
  }

  // Idle → start recording
  const ok = await speech.startCapture()
  if (!ok) return

  recordingSeconds.value = 0
  recordTimer = setInterval(() => { recordingSeconds.value++ }, 1000)
}

function handleCameraClick() {
  hardware.toggleCamera()
}

onUnmounted(() => {
  if (recordTimer) clearInterval(recordTimer)
})
</script>

<template>
  <div class="flex items-center gap-3 p-4 border-t border-border">
    <!-- Voice toggle: single button, start/stop -->
    <button
      class="p-3 rounded-full transition-all relative"
      :class="speech.isRecording.value
        ? 'bg-red-500 text-white animate-pulse'
        : isProcessingVoice
          ? 'bg-primary/30 text-primary'
          : 'bg-accent text-muted-foreground hover:bg-accent/80'"
      :disabled="isProcessingVoice"
      @click="handleVoiceToggle"
      title="语音输入"
    >
      <svg v-if="isProcessingVoice" class="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
      </svg>
      <svg v-else class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15c-.08-.49-.49-.85-.98-.85-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"/>
      </svg>
    </button>

    <!-- Camera toggle -->
    <button
      :class="[
        'p-3 rounded-full transition-all',
        hardware.hardware.camera
          ? 'bg-green-500 text-white'
          : 'bg-accent text-muted-foreground hover:bg-accent/80'
      ]"
      @click="handleCameraClick"
      title="摄像头"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
      </svg>
    </button>

    <div class="flex-1"></div>

    <!-- Status -->
    <div class="text-xs text-muted-foreground text-right">
      <template v-if="speech.isRecording.value">
        <span class="text-red-400">● 录音中 {{ formatTime(recordingSeconds) }}</span>
      </template>
      <template v-else-if="isProcessingVoice">
        <span class="text-primary">识别中...</span>
      </template>
      <template v-else>
        <span class="text-primary/50">点击麦克风开始</span>
      </template>
    </div>
  </div>
</template>
