<script setup lang="ts">
import { useHardwareStore } from '@/stores/hardware'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { ref } from 'vue'

const hardware = useHardwareStore()
const speech = useSpeechRecognition()

const isProcessingVoice = ref(false)

async function handleMicClick() {
  if (speech.isRecording.value) {
    speech.stopRecording()
  } else {
    speech.startRecording()
  }
}

async function handleVoiceInput() {
  if (isProcessingVoice.value) return

  isProcessingVoice.value = true
  try {
    const response = await speech.processVoiceInput()
    if (response) {
      speech.speak(response)
    }
  } finally {
    isProcessingVoice.value = false
  }
}

function handleCameraClick() {
  hardware.toggleCamera()
}
</script>

<template>
  <div class="flex items-center gap-3 p-4 border-t border-border">
    <button
      :class="[
        'p-3 rounded-full transition-all relative',
        speech.isRecording.value
          ? 'bg-red-500 text-white animate-pulse'
          : 'bg-accent text-muted-foreground hover:bg-accent/80'
      ]"
      @click="handleMicClick"
      title="语音识别"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15c-.08-.49-.49-.85-.98-.85-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"/>
      </svg>
      <span
        v-if="speech.isRecording.value"
        class="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full animate-ping"
      ></span>
    </button>

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

    <button
      class="p-3 rounded-full bg-accent text-muted-foreground hover:bg-accent/80 transition-all"
      title="处理语音输入"
      :disabled="isProcessingVoice"
      @click="handleVoiceInput"
    >
      <svg
        :class="['w-5 h-5', isProcessingVoice && 'animate-spin']"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
      </svg>
    </button>

    <div class="flex-1"></div>

    <div class="text-xs text-muted-foreground">
      <span v-if="speech.isRecording.value">正在录音...</span>
      <span v-else-if="isProcessingVoice">处理中...</span>
      <span v-else-if="speech.transcript.value">{{ speech.transcript.value }}</span>
    </div>
  </div>
</template>

