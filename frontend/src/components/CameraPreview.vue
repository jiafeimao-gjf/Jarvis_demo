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
const autoCapture = ref(false)
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

function toggleCapture() {
  if (autoCapture.value) {
    // Stop
    if (captureTimer) { clearInterval(captureTimer); captureTimer = null }
    autoCapture.value = false
    captureError.value = ''
    queueLength.value = 0
  } else {
    // Start
    captureError.value = ''
    captureTimer = setInterval(analyzeAndChat, 30000)
    autoCapture.value = true
  }
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

function stopCapture() {
  if (captureTimer) { clearInterval(captureTimer); captureTimer = null }
  autoCapture.value = false
  frameQueue = []
  queueLength.value = 0
  isCapturing.value = false
  isProcessing.value = false
}

// Clean up when camera turns off
watch(
  () => hardware.hardware.camera,
  (active) => { if (!active) stopCapture() },
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
        <div class="flex items-center gap-2">
          <button
            class="w-6 h-6 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-red-500 transition-colors shrink-0"
            @click="handleClose"
          >
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
          <span class="text-xs text-white/80 flex-1 truncate">摄像头</span>

          <button
            class="px-2 py-0.5 text-xs rounded-full transition-colors shrink-0 border"
            :class="autoCapture
              ? 'bg-red-500/20 text-red-400 border-red-500/50'
              : 'bg-primary/20 text-primary border-primary/40 hover:bg-primary/30'"
            @click="toggleCapture"
          >
            <template v-if="autoCapture">
              停止 · {{ queueLength > 0 ? `队列${queueLength}` : (isCapturing ? '分析中' : '等待中') }}
            </template>
            <template v-else>开始分析</template>
          </button>
        </div>

        <p v-if="captureError" class="text-xs text-red-400">{{ captureError }}</p>
      </div>
    </div>
  </Transition>
</template>
