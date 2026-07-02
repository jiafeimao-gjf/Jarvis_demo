<script setup lang="ts">
// SubagentSessionPanel.vue — 右侧抽屉, 显示 subagent 完整执行轨迹
// 支持单 session 和批量 (tab 切换) 两种模式
import { ref, watch, computed, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

interface SubSession {
  conversation_id: string
  topic?: string
  subagent_role?: string
  subagent_task?: string
  parent_conversation_id?: string
  session_kind: string
  messages: Array<{
    message_id: string
    role: string
    content: string
    thinking?: string
    image?: string
    timestamp: string
  }>
  created_at?: string
}

const props = defineProps<{
  subSessionId: string | null
  batchIds?: string[]
  initialTab?: number
}>()

const emit = defineEmits<{ close: [] }>()

const activeTab = ref(props.initialTab ?? 0)
const session = ref<SubSession | null>(null)
const batchSessions = ref<SubSession[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const isBatch = computed(() => (props.batchIds?.length ?? 0) > 1)
const currentSession = computed<SubSession | null>(() => {
  if (isBatch.value) {
    return batchSessions.value[activeTab.value] ?? null
  }
  return session.value
})

const ROLE_META: Record<string, { icon: string; label: string }> = {
  researcher: { icon: '🔬', label: 'Researcher' },
  coder:      { icon: '💻', label: 'Coder' },
  reviewer:   { icon: '🔍', label: 'Reviewer' },
  summarizer: { icon: '📝', label: 'Summarizer' },
  planner:    { icon: '📐', label: 'Planner' },
  general:    { icon: '🤖', label: 'General' },
}

marked.setOptions({ breaks: true, gfm: true })
const ALLOWED_TAGS = ['p','br','strong','em','del','s','code','pre','ul','ol','li','blockquote','a','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td','hr','img','span','div']
const ALLOWED_ATTR = ['href','target','src','alt','class','id']

function renderMarkdown(text: string): string {
  if (!text) return ''
  const raw = marked.parse(text) as string
  return DOMPurify.sanitize(raw, { ALLOWED_TAGS, ALLOWED_ATTR })
}

async function fetchSession(id: string): Promise<SubSession | null> {
  try {
    const res = await fetch(`/api/memory/sub_session/${id}`)
    if (!res.ok) {
      if (res.status === 404) throw new Error('子会话不存在')
      throw new Error(`HTTP ${res.status}`)
    }
    return await res.json()
  } catch (e) {
    error.value = (e as Error).message
    return null
  }
}

watch(
  () => [props.subSessionId, props.batchIds],
  async ([id, batch]) => {
    error.value = null
    if (batch && Array.isArray(batch) && batch.length > 1) {
      // 批量模式: 一次性加载所有
      loading.value = true
      batchSessions.value = []
      const results = await Promise.all(batch.map(bid => fetchSession(bid)))
      batchSessions.value = results.filter((s): s is SubSession => s !== null)
      loading.value = false
      activeTab.value = props.initialTab ?? 0
    } else if (typeof id === 'string') {
      // 单 session
      loading.value = true
      session.value = null
      session.value = await fetchSession(id)
      loading.value = false
    }
  },
  { immediate: true }
)

function close() {
  emit('close')
}

function onBackdropClick(e: MouseEvent) {
  if (e.target === e.currentTarget) close()
}

function formatTime(ts?: string) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

onUnmounted(() => {
  document.body.style.overflow = ''
})

// 锁定背景滚动
watch(
  () => props.subSessionId ?? props.batchIds?.length,
  (val) => {
    if (val) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
  }
)
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <div
      v-if="subSessionId || (batchIds && batchIds.length > 0)"
      class="fixed inset-0 bg-black/30 z-40"
      @click="onBackdropClick"
    ></div>

    <!-- Drawer -->
    <div
      v-if="subSessionId || (batchIds && batchIds.length > 0)"
      class="fixed top-0 right-0 bottom-0 w-[640px] max-w-[95vw] bg-background
             border-l border-border shadow-2xl z-50 flex flex-col"
    >
      <!-- Header -->
      <div class="flex items-center gap-2 px-4 py-3 border-b border-border bg-card">
        <span class="text-base">
          {{ ROLE_META[currentSession?.subagent_role || 'general']?.icon || '🤖' }}
        </span>
        <span class="text-sm font-medium">
          {{ ROLE_META[currentSession?.subagent_role || 'general']?.label || 'Subagent' }} 会话
        </span>
        <span class="text-xs text-muted-foreground flex-1 truncate">
          {{ currentSession?.subagent_task || currentSession?.topic }}
        </span>
        <button
          @click="close"
          class="text-muted-foreground hover:text-foreground w-7 h-7 rounded flex items-center justify-center hover:bg-muted"
          title="关闭"
        >
          ✕
        </button>
      </div>

      <!-- Batch tabs -->
      <div
        v-if="isBatch && batchSessions.length > 0"
        class="flex border-b border-border overflow-x-auto bg-muted/20"
      >
        <button
          v-for="(s, i) in batchSessions"
          :key="s.conversation_id"
          @click="activeTab = i"
          :class="[
            'px-3 py-2 text-xs whitespace-nowrap border-b-2 transition-colors',
            activeTab === i
              ? 'border-primary text-foreground bg-background'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          ]"
        >
          <span class="mr-1">{{ ROLE_META[s.subagent_role || 'general']?.icon }}</span>
          子代理 {{ i + 1 }}: {{ (s.subagent_task || '').slice(0, 30) }}{{ (s.subagent_task || '').length > 30 ? '…' : '' }}
        </button>
      </div>

      <!-- Sub-session metadata -->
      <div
        v-if="currentSession"
        class="px-4 py-2 border-b border-border bg-muted/10 text-xs text-muted-foreground space-y-0.5"
      >
        <div>📌 会话 ID: <code class="text-foreground/70">{{ currentSession.conversation_id.slice(0, 8) }}...</code></div>
        <div v-if="currentSession.parent_conversation_id">
          🔗 父会话: <code class="text-foreground/70">{{ currentSession.parent_conversation_id.slice(0, 8) }}...</code>
        </div>
        <div>🕐 创建: {{ formatTime(currentSession.created_at) }}</div>
      </div>

      <!-- Body: messages -->
      <div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        <div v-if="loading" class="text-center text-muted-foreground py-8">
          加载中…
        </div>
        <div v-else-if="error" class="text-center text-red-600 py-8">
          ❌ {{ error }}
        </div>
        <div v-else-if="currentSession" class="space-y-2">
          <div
            v-for="m in currentSession.messages"
            :key="m.message_id"
            :class="[
              'rounded-lg p-3 text-sm border border-l-2 border-l-violet-500/60',
              m.role === 'user'
                ? 'bg-primary/5 border-primary/20'
                : m.role === 'assistant'
                  ? 'bg-muted/40 border-border'
                  : 'bg-amber-50/40 border-amber-200 dark:bg-amber-900/10 dark:border-amber-800'
            ]"
          >
            <div class="flex items-center gap-2 text-[11px] text-muted-foreground mb-1">
              <span
                class="px-1.5 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap
                       bg-violet-500/15 text-violet-600 dark:text-violet-400
                       border border-violet-500/25"
                :title="`子代理会话${currentSession?.subagent_role ? ' · ' + currentSession.subagent_role : ''}`"
              >
                SUB {{ ROLE_META[currentSession?.subagent_role || 'general']?.icon }} 子代理
              </span>
              <span class="font-medium">{{ m.role }}</span>
              <span>·</span>
              <span>{{ formatTime(m.timestamp) }}</span>
            </div>
            <details v-if="m.thinking" class="mb-2 text-xs">
              <summary class="text-muted-foreground cursor-pointer hover:text-foreground italic">
                💭 thinking
              </summary>
              <pre class="mt-1 p-2 bg-muted rounded text-[11px] whitespace-pre-wrap max-h-32 overflow-y-auto">{{ m.thinking }}</pre>
            </details>
            <div
              v-if="m.content"
              class="markdown-content"
              v-html="renderMarkdown(m.content)"
            ></div>
            <div v-if="m.image" class="mt-2">
              <img :src="m.image" class="max-w-full rounded" alt="attachment" />
            </div>
          </div>
        </div>
        <div v-else class="text-center text-muted-foreground py-8">
          无消息
        </div>
      </div>

      <!-- Footer -->
      <div class="px-4 py-2 border-t border-border bg-muted/10 text-xs text-muted-foreground flex justify-between">
        <span>
          {{ currentSession?.messages?.length || 0 }} 条消息
        </span>
        <span>ESC 或点击背景关闭</span>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.markdown-content {
  word-break: break-word;
  color: hsl(var(--foreground));
}
.markdown-content :deep(pre) {
  background: hsl(var(--muted));
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  padding: 0.75rem;
  margin: 0.5rem 0;
  overflow-x: auto;
  font-size: 0.8em;
}
.markdown-content :deep(code) {
  font-size: 0.875em;
  background: hsl(var(--muted));
  padding: 0.15em 0.4em;
  border-radius: 0.25em;
}
</style>