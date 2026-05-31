<script setup lang="ts">
import { ref, onUnmounted, watch } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useChatStore } from '@/stores/chat'
import { useApi } from '@/composables/useApi'

const hardware = useHardwareStore()
const chatStore = useChatStore()
const api = useApi()

const isCapturing = ref(false)
const captureError = ref('')
const videoRef = ref<HTMLVideoElement | null>(null)
let captureTimer: ReturnType<typeof setInterval> | null = null

function handleClose() {
  stopCapture()
  hardware.stopCamera()
}

function captureFrame(): string | null {
  const videoEl = videoRef.value
  if (!videoEl || videoEl.readyState < 2) return null

  const canvas = document.createElement('canvas')
  canvas.width = videoEl.videoWidth || 640
  canvas.height = videoEl.videoHeight || 480
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.7)
}

async function analyzeAndChat() {
  if (isCapturing.value || chatStore.isLoading) return
  isCapturing.value = true

  try {
    const frameBase64 = captureFrame()
    if (!frameBase64) {
      captureError.value = '无法获取摄像头画面'
      isCapturing.value = false
      return
    }
    // Remove data:image/jpeg;base64, prefix
    const base64Data = frameBase64.split(',')[1]
    if (!base64Data) {
      captureError.value = '图像数据无效'
      isCapturing.value = false
      return
    }

    captureError.value = ''
    const result = await api.analyzeCameraFrame(base64Data, '请描述这张图片中的内容')

    if (result.analysis) {
      chatStore.addMessage('user', `📷 [图片分析] ${result.analysis}`)
    }
  } catch (e) {
    captureError.value = `分析失败: ${(e as Error).message}`
  } finally {
    isCapturing.value = false
  }
}

function startCapture() {
  if (captureTimer) return
  // Capture and analyze every 5 seconds
  captureTimer = setInterval(analyzeAndChat, 5000)
}

function stopCapture() {
  if (captureTimer) {
    clearInterval(captureTimer)
    captureTimer = null
  }
  isCapturing.value = false
}

// Start/stop capture when camera state changes
watch(
  () => hardware.hardware.camera,
  (active) => {
    if (active) startCapture()
    else stopCapture()
  },
  { immediate: true }
)

onUnmounted(() => stopCapture())
</script>

<template>
  <Transition
    enter-active-class="transition duration-300 ease-out"
    enter-from-class="opacity-0 scale-95"
    enter-to-class="opacity-100 scale-100"
    leave-active-class="transition duration-300 ease-in"
    leave-from-class="opacity-100 scale-100"
    leave-to-class="opacity-0 scale-95"
  >
    <div
      v-if="hardware.hardware.camera && hardware.cameraStream"
      class="fixed bottom-20 right-6 w-72 rounded-xl border-2 border-primary overflow-hidden shadow-2xl bg-secondary z-50"
    >
      <!-- Hidden canvas for frame capture -->
      <video
        ref="videoRef"
        :srcObject="hardware.cameraStream"
        autoplay
        playsinline
        muted
        class="w-full h-48 object-cover"
      />
      <div class="p-3 space-y-2">
        <div class="flex items-center justify-between">
          <button
            class="w-7 h-7 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-black/90 transition-colors"
            @click="handleClose"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
          <span class="text-xs text-white/80">摄像头</span>
          <button
            class="px-2 py-1 text-xs rounded-full transition-colors"
            :class="isCapturing
              ? 'bg-primary/30 text-primary border border-primary/50'
              : 'bg-white/10 text-white/60 border border-white/20'"
            @click="analyzeAndChat"
            :disabled="isCapturing || chatStore.isLoading"
          >
            {{ isCapturing ? '分析中...' : '📸 分析' }}
          </button>
        </div>
        <p v-if="captureError" class="text-xs text-red-400">{{ captureError }}</p>
        <p class="text-xs text-white/50">每 5 秒自动分析 → 对话</p>
      </div>
    </div>
  </Transition>
</template>
