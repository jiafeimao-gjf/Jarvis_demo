<script setup lang="ts">
// SubagentCard.vue — 主会话里 subagent 调用的紧凑卡片
// 点击 → 触发 openSession 或 openBatch 事件, 父组件打开 SubagentSessionPanel
import { computed } from 'vue'

interface SubagentItem {
  role: string
  task: string
  output?: string
  success?: boolean
  elapsed_ms?: number
  error?: string
  sub_session_id?: string
}

interface SubagentData {
  role?: string
  task?: string
  context?: string
  mode?: string
  results?: SubagentItem[]
  reduced_output?: string
  status: 'success' | 'partial' | 'error'
  elapsed_ms?: number
  sub_session_id?: string
  sub_session_ids?: string[]
}

const props = defineProps<{
  subagent: SubagentData
}>()

const emit = defineEmits<{
  openSession: [subSessionId: string]
  openBatch: [subSessionIds: string[], activeIndex: number]
}>()

const ROLE_META: Record<string, { icon: string; bg: string; text: string; label: string }> = {
  researcher: { icon: '🔬', bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-300', label: 'Researcher' },
  coder:      { icon: '💻', bg: 'bg-green-100 dark:bg-green-900/40', text: 'text-green-700 dark:text-green-300', label: 'Coder' },
  reviewer:   { icon: '🔍', bg: 'bg-purple-100 dark:bg-purple-900/40', text: 'text-purple-700 dark:text-purple-300', label: 'Reviewer' },
  summarizer: { icon: '📝', bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300', label: 'Summarizer' },
  planner:    { icon: '📐', bg: 'bg-cyan-100 dark:bg-cyan-900/40', text: 'text-cyan-700 dark:text-cyan-300', label: 'Planner' },
  general:    { icon: '🤖', bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-700 dark:text-gray-300', label: 'General' },
}

const MODE_META: Record<string, { icon: string; bg: string; text: string; label: string }> = {
  sequential: { icon: '➡️', bg: 'bg-slate-100 dark:bg-slate-800', text: 'text-slate-700 dark:text-slate-300', label: 'sequential' },
  parallel:   { icon: '⚡', bg: 'bg-yellow-100 dark:bg-yellow-900/40', text: 'text-yellow-700 dark:text-yellow-300', label: 'parallel' },
  map_reduce: { icon: '🗺', bg: 'bg-orange-100 dark:bg-orange-900/40', text: 'text-orange-700 dark:text-orange-300', label: 'map_reduce' },
}

const isBatch = computed(() => Array.isArray(props.subagent.results) && props.subagent.results.length > 0)
const singleRole = computed(() => props.subagent.role || 'general')

const summaryText = computed(() => {
  if (props.subagent.reduced_output) {
    return props.subagent.reduced_output.slice(0, 200)
  }
  if (props.subagent.output) {
    return props.subagent.output.slice(0, 200)
  }
  return ''
})

const successCount = computed(() => {
  if (!isBatch.value) return null
  return props.subagent.results!.filter(r => r.success).length
})

const totalCount = computed(() => {
  if (!isBatch.value) return null
  return props.subagent.results!.length
})

const hasAnySubSession = computed(() => {
  if (isBatch.value) {
    return (props.subagent.sub_session_ids?.length ?? 0) > 0 ||
           props.subagent.results!.some(r => r.sub_session_id)
  }
  return !!props.subagent.sub_session_id
})

function openSingle() {
  if (props.subagent.sub_session_id) {
    emit('openSession', props.subagent.sub_session_id)
  }
}

function openBatchAt(idx: number) {
  const ids = props.subagent.sub_session_ids ||
    props.subagent.results!.map(r => r.sub_session_id).filter(Boolean) as string[]
  if (ids.length > 0) {
    emit('openBatch', ids, idx)
  }
}

function truncate(s: string | undefined, n: number): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}
</script>

<template>
  <div class="border border-border rounded-xl overflow-hidden bg-card my-2 max-w-[85%]">
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 bg-muted/40 border-b border-border text-xs">
      <!-- Role badge (单任务) -->
      <span
        v-if="!isBatch"
        :class="['px-1.5 py-0.5 rounded font-medium', ROLE_META[singleRole]?.bg, ROLE_META[singleRole]?.text]"
      >
        {{ ROLE_META[singleRole]?.icon }} {{ ROLE_META[singleRole]?.label }}
      </span>

      <!-- Mode badge -->
      <span
        v-if="subagent.mode && subagent.mode !== 'single'"
        :class="['px-1.5 py-0.5 rounded text-[10px]', MODE_META[subagent.mode]?.bg, MODE_META[subagent.mode]?.text]"
      >
        {{ MODE_META[subagent.mode]?.icon }} {{ MODE_META[subagent.mode]?.label }}
      </span>

      <!-- Batch counter -->
      <span v-if="isBatch" class="text-muted-foreground">
        🤖 {{ totalCount }} 个子代理
      </span>

      <span class="flex-1"></span>

      <!-- Status -->
      <span v-if="subagent.status === 'success'" class="text-green-600 dark:text-green-400 text-xs">
        ✅
      </span>
      <span v-else-if="subagent.status === 'partial'" class="text-amber-600 dark:text-amber-400 text-xs">
        ⚠️ {{ successCount }}/{{ totalCount }}
      </span>
      <span v-else class="text-red-600 dark:text-red-400 text-xs">
        ❌
      </span>

      <!-- Timing -->
      <span v-if="subagent.elapsed_ms" class="text-muted-foreground text-[10px]">
        ⏱ {{ (subagent.elapsed_ms / 1000).toFixed(1) }}s
      </span>
    </div>

    <!-- Body -->
    <div class="px-3 py-2 text-xs space-y-1">
      <div class="text-muted-foreground">
        📋 {{ truncate(subagent.task, 80) }}
      </div>
      <div v-if="summaryText" class="text-foreground/80 line-clamp-2">
        {{ summaryText }}{{ summaryText.length >= 200 ? '…' : '' }}
      </div>
      <div v-if="subagent.context" class="text-muted-foreground/70 text-[11px]">
        💭 上下文: {{ truncate(subagent.context, 60) }}
      </div>
    </div>

    <!-- Batch subagent list -->
    <div v-if="isBatch" class="border-t border-border/50 px-3 py-2 space-y-1">
      <button
        v-for="(r, i) in subagent.results"
        :key="i"
        @click="openBatchAt(i)"
        :disabled="!r.sub_session_id"
        class="w-full flex items-center gap-2 px-2 py-1 rounded text-[11px] hover:bg-muted/60 transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span :class="['px-1 py-0.5 rounded', ROLE_META[r.role]?.bg, ROLE_META[r.role]?.text]">
          {{ ROLE_META[r.role]?.icon }} {{ ROLE_META[r.role]?.label }}
        </span>
        <span class="text-muted-foreground truncate flex-1">
          {{ truncate(r.task, 50) }}
        </span>
        <span v-if="r.elapsed_ms" class="text-muted-foreground text-[10px]">
          ⏱ {{ (r.elapsed_ms / 1000).toFixed(1) }}s
        </span>
        <span :class="r.success ? 'text-green-600' : 'text-red-600'">
          {{ r.success ? '✅' : '❌' }}
        </span>
        <span v-if="r.sub_session_id" class="text-primary">→</span>
      </button>
    </div>

    <!-- Action footer -->
    <div v-if="hasAnySubSession" class="px-3 py-1.5 border-t border-border/50 bg-muted/20">
      <button
        v-if="!isBatch"
        @click="openSingle"
        class="text-xs text-primary hover:underline"
      >
        查看完整会话 →
      </button>
      <div v-else class="text-xs text-muted-foreground">
        点击上方任一子代理查看完整会话
      </div>
    </div>
  </div>
</template>