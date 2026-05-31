<script setup lang="ts">
import { ref, onUnmounted, watch } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useChatStore } from '@/stores/chat'
import { useApi } from '@/composables/useApi'

const hardware = useHardwareStore()
const chatStore = useChatStore()
const api = useApi()

const isCapturing = ref(false)
const isProcessing = ref(false)
const autoCapture = ref(true)   // auto mode on by default
const queueLength = ref(0)
const captureError = ref('')
const videoRef = ref<HTMLVideoElement | null>(null)
let captureTimer: ReturnType<typeof setInterval> | null = null
let frameQueue: Array<{ apiData: string; displayUrl: string }> = []
const MAX_QUEUE = 2

function handleClose() {
  stopCapture()
  hardware.stopCamera()
}

function toggleAutoCapture() {
  if (autoCapture.value) {
    stopAutoTimer()
    autoCapture.value = false
  } else {
    startAutoTimer()
    autoCapture.value = true
  }
}

function stopAutoTimer() {
  if (captureTimer) {
    clearInterval(captureTimer)
    captureTimer = null
  }
}

function startAutoTimer() {
  if (captureTimer) return
  captureTimer = setInterval(analyzeAndChat, 30000)
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

function analyzeAndChat() {
  // Capture frame and enqueue — non-blocking
  const frameBase64 = captureFrame()
  if (!frameBase64) {
    captureError.value = '无法获取摄像头画面'
    return
  }
  const base64Data = frameBase64.split(',')[1]
  if (!base64Data) {
    captureError.value = '图像数据无效'
    return
  }

  // Enqueue frame + preview (drop oldest if full)
  if (frameQueue.length >= MAX_QUEUE) {
    frameQueue.shift()
  }
  frameQueue.push({ apiData: base64Data, displayUrl: frameBase64 })
  queueLength.value = frameQueue.length
  captureError.value = ''

  if (!isProcessing.value) {
    processQueue()
  }
}

async function processQueue() {
  isProcessing.value = true

  while (frameQueue.length > 0) {
    const item = frameQueue[0]
    isCapturing.value = true

    try {
      const result = await api.analyzeCameraFrame(item.apiData, '请描述这张图片中的内容')
      if (result.analysis) {
        chatStore.addMessage(
          'assistant',
          `📷 [图片分析]\n\n${result.analysis}`,
          item.displayUrl
        )
      } else {
        captureError.value = '分析返回空结果'
      }
      frameQueue.shift()
    } catch (e) {
      captureError.value = `分析失败: ${(e as Error).message}`
      frameQueue.shift()
    } finally {
      isCapturing.value = false
      queueLength.value = frameQueue.length
    }
  }

  isProcessing.value = false
}

function startCapture() {
  if (captureTimer) return
  autoCapture.value = true
  startAutoTimer()
}

function stopCapture() {
  stopAutoTimer()
  autoCapture.value = false
  frameQueue = []
  queueLength.value = 0
  isCapturing.value = false
  isProcessing.value = false
}

// Auto-start capture when camera activates
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
        <!-- Controls row -->
        <div class="flex items-center gap-2">
          <button
            class="w-6 h-6 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-red-500 transition-colors shrink-0"
            @click="handleClose"
          >
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>

          <span class="text-xs text-white/80 truncate flex-1">摄像头</span>

          <!-- Stop/start auto toggle -->
          <button
            class="px-2 py-0.5 text-xs rounded-full transition-colors shrink-0"
            :class="autoCapture
              ? 'bg-red-500/30 text-red-400 border border-red-500/50 hover:bg-red-500/50'
              : 'bg-green-500/30 text-green-400 border border-green-500/50 hover:bg-green-500/50'"
            @click="toggleAutoCapture"
          >
            {{ autoCapture ? '⏸ 停止' : '▶ 开始' }}
          </button>

          <!-- Manual snap button -->
          <button
            class="px-2 py-0.5 text-xs rounded-full transition-colors shrink-0"
            :class="isCapturing
              ? 'bg-primary/30 text-primary border border-primary/50'
              : 'bg-white/10 text-white/60 border border-white/20 hover:bg-white/20'"
            @click="analyzeAndChat"
            :disabled="isCapturing"
          >
            {{ isCapturing ? '分析中...' : '📸' }}
          </button>
        </div>

        <p v-if="captureError" class="text-xs text-red-400">{{ captureError }}</p>
        <p class="text-xs text-white/50">
          {{ autoCapture ? '每 30s 自动分析' : '已暂停自动分析' }}
          <span v-if="queueLength > 0" class="text-primary ml-1">({{ queueLength }})</span>
        </p>
      </div>
    </div>
  </Transition>
</template>
