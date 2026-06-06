<script setup lang="ts">
import { ref, onUnmounted, watch, onMounted } from 'vue'
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

// Drag state
const panelRef = ref<HTMLElement | null>(null)
const panelPos = ref<{ x: number; y: number } | null>(null)  // null = use default (CSS class)
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let dragOriginX = 0
let dragOriginY = 0

const POS_STORAGE_KEY = 'jarvis_camera_pos_v1'

function loadPosition(): { x: number; y: number } | null {
  try {
    const raw = sessionStorage.getItem(POS_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
      return parsed
    }
  } catch { /* ignore */ }
  return null
}

function savePosition(pos: { x: number; y: number }) {
  try {
    sessionStorage.setItem(POS_STORAGE_KEY, JSON.stringify(pos))
  } catch { /* ignore */ }
}

function clampPosition(x: number, y: number): { x: number; y: number } {
  // Keep panel within viewport — at least 24px visible from each edge
  const w = panelRef.value?.offsetWidth ?? 288
  const h = panelRef.value?.offsetHeight ?? 220
  const maxX = Math.max(0, window.innerWidth - w - 8)
  const maxY = Math.max(0, window.innerHeight - h - 8)
  return {
    x: Math.min(Math.max(8, x), maxX),
    y: Math.min(Math.max(8, y), maxY),
  }
}

function onDragHandleMouseDown(e: MouseEvent) {
  // Only left button
  if (e.button !== 0) return
  isDragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  const cur = panelPos.value ?? defaultPos()
  dragOriginX = cur.x
  dragOriginY = cur.y
  // Use current pos as initial so the panel doesn't jump on first drag
  if (!panelPos.value) panelPos.value = cur
  e.preventDefault()
}

function defaultPos(): { x: number; y: number } {
  // Approximate the default `fixed bottom-20 right-6` position
  const w = panelRef.value?.offsetWidth ?? 288
  const h = panelRef.value?.offsetHeight ?? 220
  return { x: window.innerWidth - w - 24, y: window.innerHeight - h - 80 }
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  const next = clampPosition(dragOriginX + dx, dragOriginY + dy)
  panelPos.value = next
}

function onMouseUp() {
  if (!isDragging) return
  isDragging = false
  if (panelPos.value) savePosition(panelPos.value)
}

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
  // Un-mirror: since the <video> is shown with scaleX(-1), the captured pixels
  // would also be mirrored. Pre-flip horizontally so the model sees the true
  // orientation of the subject.
  ctx.save()
  ctx.translate(canvas.width, 0)
  ctx.scale(-1, 1)
  ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height)
  ctx.restore()
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

onMounted(() => {
  // Restore position from sessionStorage
  const saved = loadPosition()
  if (saved) {
    panelPos.value = clampPosition(saved.x, saved.y)
  }
  // Global mouse listeners so drag continues outside the handle
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
})

onUnmounted(() => {
  stopCapture()
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
})
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
      ref="panelRef"
      class="fixed w-72 rounded-xl border-2 border-primary overflow-hidden shadow-2xl bg-secondary z-50 select-none"
      :class="panelPos ? '' : 'bottom-20 right-6'"
      :style="panelPos
        ? { left: panelPos.x + 'px', top: panelPos.y + 'px', transition: isDragging ? 'none' : 'left 0.2s, top 0.2s' }
        : undefined"
    >
      <!-- Drag handle bar -->
      <div
        class="h-7 bg-black/60 flex items-center justify-center cursor-move"
        @mousedown="onDragHandleMouseDown"
        title="按住拖动"
      >
        <span class="text-[10px] text-white/50 tracking-widest uppercase">摄像头 · 拖动</span>
      </div>
      <!-- Mirrored video preview (user-facing) -->
      <video
        ref="videoRef"
        :srcObject="hardware.cameraStream"
        autoplay
        playsinline
        muted
        class="w-full h-48 object-cover"
        style="transform: scaleX(-1);"
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
