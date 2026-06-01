<script setup lang="ts">
import { computed, ref, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Message } from '@/types'
import { formatTime } from '@/lib/utils'

const props = defineProps<{
  message: Message
}>()

const isUser = computed(() => props.message.role === 'user')
const isTool = computed(() => props.message.role === 'tool')
const isToolResult = computed(() => props.message.role === 'tool_result')

const toolInfo = computed(() => {
  if (!isTool.value) return null
  try { return JSON.parse(props.message.content) } catch { return null }
})
const toolResultInfo = computed(() => {
  if (!isToolResult.value) return { text: props.message.content }
  const t = props.message.content
  const m = t.match(/^\[(工具结果|工具错误)\]\s*(\S+?):\s*(.*)/s)
  if (m) return { status: m[1] === '工具结果' ? 'success' : 'error', tool: m[2], detail: m[3] }
  return { status: 'info', tool: '', detail: t }
})

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,
  gfm: true
})

const ALLOWED_TAGS = ['p','br','strong','em','del','s','code','pre','ul','ol','li','blockquote','a','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td','hr','img','span','div']
const ALLOWED_ATTR = ['href','target','src','alt','class','id']

// Render markdown content for assistant messages, plain text for user
const renderedContent = computed(() => {
  if (isUser.value) {
    return props.message.content
  }
  const raw = marked.parse(props.message.content) as string
  return DOMPurify.sanitize(raw, { ALLOWED_TAGS, ALLOWED_ATTR })
})

// ── Image fullscreen viewer ──────────────────────────────────────
const showViewer = ref(false)
const viewerZoom = ref(1)
const MIN_ZOOM = 0.5
const MAX_ZOOM = 4
const isSpeaking = ref(false)

function speakContent() {
  if (!('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(props.message.content)
  utterance.lang = 'zh-CN'
  utterance.rate = 1.0
  isSpeaking.value = true
  utterance.onend = () => { isSpeaking.value = false }
  utterance.onerror = () => { isSpeaking.value = false }
  speechSynthesis.speak(utterance)
}

function openViewer() {
  viewerZoom.value = 1
  showViewer.value = true
  document.body.style.overflow = 'hidden'
}
function closeViewer() {
  showViewer.value = false
  document.body.style.overflow = ''
}
function zoomIn()  { viewerZoom.value = Math.min(viewerZoom.value * 1.5, MAX_ZOOM) }
function zoomOut() { viewerZoom.value = Math.max(viewerZoom.value / 1.5, MIN_ZOOM) }
function zoomReset() { viewerZoom.value = 1 }
function onWheel(e: WheelEvent) {
  e.preventDefault()
  e.deltaY < 0 ? zoomIn() : zoomOut()
}

onUnmounted(() => { document.body.style.overflow = '' })
</script>

<template>
  <div
    :class="[
      'flex flex-col px-4 py-3 max-w-[70%] break-words',
      isUser
        ? 'items-end self-end'
        : 'items-start self-start'
    ]"
  >
    <!-- Chat bubble -->
    <div
      :class="[
        'rounded-2xl px-4 py-3 relative overflow-hidden',
        isUser
          ? 'bg-gradient-to-br from-primary/30 to-primary/10 border border-primary/30'
          : isTool || isToolResult
            ? 'bg-muted border border-border max-w-[85%]'
            : 'bg-gradient-to-br from-secondary/80 to-secondary/40 border border-primary/20'
      ]"
    >
      <!-- 图片预览：摄像头分析结果的视频帧 -->
      <div v-if="message.image" class="mb-3 -mx-4 -mt-3">
        <img
          :src="message.image"
          alt="分析画面"
          class="w-full max-h-80 object-contain rounded-t-2xl border-b border-primary/20 bg-black/50 cursor-zoom-in hover:opacity-90 transition-opacity"
          loading="lazy"
          @click="openViewer"
        />
        <div class="text-[10px] text-primary/40 px-4 mt-1">📸 分析画面 · 点击放大</div>
      </div>

      <!-- Fullscreen image viewer -->
      <Teleport to="body">
        <div
          v-if="showViewer"
          class="fixed inset-0 z-[100] bg-black/90 flex flex-col items-center justify-center"
          @click.self="closeViewer"
          @wheel="onWheel"
        >
          <!-- Toolbar -->
          <div class="absolute top-4 right-4 flex items-center gap-2 z-10">
            <button class="w-9 h-9 rounded-full bg-white/10 text-white/80 hover:bg-white/20 flex items-center justify-center text-sm" @click="zoomOut" title="缩小">−</button>
            <span class="text-white/60 text-xs w-12 text-center">{{ Math.round(viewerZoom * 100) }}%</span>
            <button class="w-9 h-9 rounded-full bg-white/10 text-white/80 hover:bg-white/20 flex items-center justify-center text-sm" @click="zoomIn" title="放大">+</button>
            <button class="w-9 h-9 rounded-full bg-white/10 text-white/80 hover:bg-white/20 flex items-center justify-center text-sm" @click="zoomReset" title="重置">⟲</button>
            <button class="w-9 h-9 rounded-full bg-white/10 text-white/80 hover:bg-white/20 flex items-center justify-center ml-4" @click="closeViewer" title="关闭">✕</button>
          </div>
          <!-- Image -->
          <img
            :src="message.image"
            alt="分析画面"
            class="max-w-[95vw] max-h-[90vh] object-contain transition-transform duration-200 select-none"
            :style="{ transform: `scale(${viewerZoom})` }"
            draggable="false"
          />
        </div>
      </Teleport>
      <!-- Thinking (collapsible) — not for tool messages -->
      <details v-if="!isUser && !isTool && !isToolResult && message.thinking" class="mb-2 text-xs">
        <summary class="text-muted-foreground/60 cursor-pointer hover:text-muted-foreground transition-colors select-none">思考过程</summary>
        <div class="mt-1 text-foreground/55 bg-muted rounded-lg p-2 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">
          {{ message.thinking }}
        </div>
      </details>
      <!-- Tool call card -->
      <div v-if="isTool && toolInfo" class="flex items-start gap-2 text-xs">
        <span class="text-foreground/50 mt-0.5">🔧</span>
        <div>
          <span class="text-foreground/80 font-medium">{{ toolInfo.tool }}.{{ toolInfo.action }}</span>
          <pre class="text-muted-foreground mt-1 text-[11px] whitespace-pre-wrap">{{ JSON.stringify(toolInfo.params, null, 2) }}</pre>
        </div>
      </div>
      <!-- Tool result card -->
      <div v-else-if="isToolResult" class="flex items-start gap-2 text-xs">
        <span class="mt-0.5">{{ toolResultInfo.status === 'success' ? '✅' : toolResultInfo.status === 'error' ? '❌' : 'ℹ️' }}</span>
        <div>
          <span :class="toolResultInfo.status === 'success' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'" class="font-medium">{{ toolResultInfo.tool }}</span>
          <pre class="text-muted-foreground mt-1 text-[11px] whitespace-pre-wrap max-h-24 overflow-y-auto">{{ toolResultInfo.detail }}</pre>
        </div>
      </div>
      <!-- User message: plain text -->
      <p v-else-if="isUser" class="text-sm leading-relaxed whitespace-pre-wrap text-foreground">{{ message.content }}</p>
      <!-- Assistant message: rendered markdown -->
      <div v-else class="text-sm leading-relaxed markdown-content text-foreground" v-html="renderedContent"></div>
    </div>

    <span
      v-if="!isTool && !isToolResult"
      :class="[
        'text-[10px] mt-1 tracking-wider',
        isUser ? 'text-muted-foreground/60 text-right' : 'text-muted-foreground/50 text-left'
      ]"
    >
      {{ formatTime(message.timestamp) }}
      <button
        v-if="!isUser"
        class="ml-2 align-middle opacity-50 hover:opacity-100 transition-opacity"
        :class="isSpeaking ? 'text-primary' : ''"
        @click="speakContent"
        :title="isSpeaking ? '播放中...' : '朗读'"
      >{{ isSpeaking ? '🔊' : '🔈' }}</button>
    </span>
  </div>
</template>

<style scoped>
.markdown-content {
  word-break: break-word;
  color: hsl(var(--foreground));
}

/* code blocks — use theme-aware muted bg, works in light & dark */
.markdown-content :deep(pre) {
  background: hsl(var(--muted));
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  padding: 0.75rem;
  margin: 0.5rem 0;
  overflow-x: auto;
  font-family: ui-monospace, monospace;
  font-size: 0.8em;
  color: hsl(var(--foreground));
}

.markdown-content :deep(code) {
  font-family: ui-monospace, monospace;
  font-size: 0.875em;
  background: hsl(var(--muted));
  padding: 0.15em 0.4em;
  border-radius: 0.25rem;
  color: hsl(var(--foreground));
}

.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
}

.markdown-content :deep(p:not(:last-child)) {
  margin-bottom: 0.75rem;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.markdown-content :deep(li) {
  margin: 0.25rem 0;
}

.markdown-content :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}
/* darker link color in light mode for readability */
.light .markdown-content :deep(a) {
  color: hsl(189, 80%, 30%);
}

.markdown-content :deep(blockquote) {
  border-left: 3px solid hsl(var(--primary) / 0.5);
  padding-left: 0.75rem;
  margin: 0.5rem 0;
  color: hsl(var(--muted-foreground));
}

.markdown-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5rem 0;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid hsl(var(--border));
  padding: 0.5rem;
}

.markdown-content :deep(th) {
  background: hsl(var(--muted));
}

.markdown-content :deep(hr) {
  border-color: hsl(var(--border));
  margin: 0.75rem 0;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  color: hsl(var(--foreground));
  font-weight: 600;
  margin: 0.75rem 0 0.5rem;
}
</style>