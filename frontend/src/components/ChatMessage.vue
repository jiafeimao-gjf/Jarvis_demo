<script setup lang="ts">
import { computed, ref, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Message } from '@/types'
import { formatTime } from '@/lib/utils'
import { useApi } from '@/composables/useApi'
import { usePCMPlayer } from '@/composables/usePCMPlayer'
import SubagentCard from './SubagentCard.vue'

const props = defineProps<{
  message: Message
}>()

const emit = defineEmits<{
  openSubagentSession: [subSessionId: string]
  openSubagentBatch: [subSessionIds: string[], activeIndex: number]
}>()

const api = useApi()
const pcmPlayer = usePCMPlayer()

const isUser = computed(() => props.message.role === 'user')
const isTool = computed(() => props.message.role === 'tool')
const isToolResult = computed(() => props.message.role === 'tool_result')

// v3: 检测 subagent 工具调用/结果, 解析为结构化对象
const isSubagentToolCall = computed(() => {
  if (!isTool.value || !toolInfo.value) return false
  return toolInfo.value.tool === 'subagent'
})

const isSubagentToolResult = computed(() => {
  if (!isToolResult.value) return false
  return /^[\[【](?:工具结果|工具错误)[\]】]\s*subagent[\s:]/i.test(props.message.content)
})

const subagentCallData = computed(() => {
  if (!toolInfo.value) return null
  const p = toolInfo.value.params || {}
  return {
    role: p.role,
    task: p.task,
    context: p.context,
    mode: p.mode,
    status: 'success' as const,
  }
})

const subagentResultData = computed(() => {
  // tool_result.content 格式: "[工具结果] subagent: {...JSON...}"
  const m = props.message.content.match(/\[(工具结果|工具错误)\]\s*subagent:\s*([\s\S]+)/)
  if (!m) return null
  try {
    const data = JSON.parse(m[2].trim())
    return {
      role: data.role,
      task: data.task,
      mode: data.mode,
      results: data.results,
      reduced_output: data.reduced_output,
      output: data.output,
      status: data.status || 'success',
      elapsed_ms: data.elapsed_ms,
      sub_session_id: data.sub_session_id,
      sub_session_ids: data.sub_session_ids,
    }
  } catch {
    return null
  }
})

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
const isSynthesizing = ref(false)
let synthAbort: { aborted: boolean } | null = null

/**
 * 朗读消息内容 — 优先用克隆声音 (F5-TTS) 合成 wav URL 播放,
 * 后端降级 (browser_tts) 时回落到浏览器 SpeechSynthesis。
 * 再次点击同一气泡可中断播放。
 *
 * 注意: 不能用 ``new Audio(url); audio.play()``, 因为浏览器 autoplay
 * 策略会在 await synthesize() (秒级到分钟级) 后拒绝 play()。
 * 改走 Web Audio API + 在 click handler 内 ensureResumed():
 * AudioContext 在用户手势内 resume 后, 跨任意 await 仍可播放。
 */
async function speakContent() {
  // 已经在读 — 停止
  if (isSpeaking.value || isSynthesizing.value) {
    stopSpeaking()
    return
  }
  const text = (props.message.content || '').trim()
  if (!text) return

  // ⭐ 在用户手势内同步 resume AudioContext, 之后跨 await 仍可播
  pcmPlayer.ensureResumed()

  // 取消浏览器 TTS 兜底, 避免和克隆声音双播放
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()

  const myAbort = { aborted: false }
  synthAbort = myAbort
  isSynthesizing.value = true
  try {
    const result = await api.synthesize(text)
    if (myAbort.aborted) return
    isSynthesizing.value = false

    if (result.type === 'voice_clone') {
      const url = api.cloneAudioUrl(result.audio_url)
      isSpeaking.value = true
      try {
        // 走 Web Audio API — 不受 autoplay 策略限制
        await pcmPlayer.playUrl(url)
        isSpeaking.value = false
      } catch (e) {
        isSpeaking.value = false
        fallbackToBrowserTTS(text)
      }
    } else {
      // 后端降级 → 浏览器 TTS
      fallbackToBrowserTTS(text)
    }
  } catch (e) {
    isSynthesizing.value = false
    fallbackToBrowserTTS(text)
  }
}

function fallbackToBrowserTTS(text: string) {
  if (!('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 1.0
  isSpeaking.value = true
  utterance.onend = () => { isSpeaking.value = false }
  utterance.onerror = () => { isSpeaking.value = false }
  speechSynthesis.speak(utterance)
}

function stopSpeaking() {
  if (synthAbort) synthAbort.aborted = true
  pcmPlayer.stop()
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  isSynthesizing.value = false
  isSpeaking.value = false
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

onUnmounted(() => {
  document.body.style.overflow = ''
  stopSpeaking()
})
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
      <!-- v3: Subagent call card -->
      <SubagentCard
        v-if="isTool && isSubagentToolCall && subagentCallData"
        :subagent="subagentCallData"
        @open-session="(id) => emit('openSubagentSession', id)"
        @open-batch="(ids, idx) => emit('openSubagentBatch', ids, idx)"
      />

      <!-- v3: Subagent result card -->
      <SubagentCard
        v-else-if="isToolResult && isSubagentToolResult && subagentResultData"
        :subagent="subagentResultData"
        @open-session="(id) => emit('openSubagentSession', id)"
        @open-batch="(ids, idx) => emit('openSubagentBatch', ids, idx)"
      />

      <!-- Tool call card -->
      <div v-else-if="isTool && toolInfo" class="flex items-start gap-2 text-xs">
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
        class="ml-2 align-middle opacity-50 hover:opacity-100 transition-opacity disabled:opacity-30"
        :class="isSpeaking || isSynthesizing ? 'text-primary' : ''"
        :disabled="isSynthesizing"
        @click="speakContent"
        :title="isSynthesizing ? '合成中...' : isSpeaking ? '点击停止' : '朗读 (克隆声音)'"
      >{{ isSynthesizing ? '⏳' : isSpeaking ? '🔊' : '🔈' }}</button>
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