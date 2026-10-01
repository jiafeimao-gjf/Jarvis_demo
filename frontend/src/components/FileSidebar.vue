<script setup lang="ts">
import { ref, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import type { FileOp } from '@/types'

const props = defineProps<{
  conversationId: string | null
}>()

const emit = defineEmits<{
  close: []
  openViewer: [file: FileOp]
}>()

const api = useApi()
const files = ref<FileOp[]>([])
const isLoading = ref(false)
const errorMsg = ref<string | null>(null)

const ACTION_META: Record<string, { icon: string; label: string; color: string }> = {
  write:  { icon: '📝', label: '写入', color: 'text-green-400' },
  edit:   { icon: '✏️',  label: '修改', color: 'text-blue-400' },
  delete: { icon: '🗑️', label: '删除', color: 'text-red-400' },
  mkdir:  { icon: '📁', label: '目录', color: 'text-yellow-400' },
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

function basename(path: string): string {
  const m = path.match(/[^/\\]+$/)
  return m ? m[0] : path
}

function dirname(path: string): string {
  const idx = path.lastIndexOf('/')
  if (idx === -1) return ''
  return path.slice(0, idx)
}

async function refresh() {
  if (!props.conversationId) {
    files.value = []
    return
  }
  isLoading.value = true
  errorMsg.value = null
  try {
    const data = await api.listSessionFiles(props.conversationId)
    files.value = data.files
  } catch (e) {
    errorMsg.value = (e as Error).message
    files.value = []
  } finally {
    isLoading.value = false
  }
}

// 切换会话 / 文件列表变化时刷新
watch(() => props.conversationId, refresh, { immediate: true })
</script>

<template>
  <aside class="w-72 shrink-0 border-l border-primary/10 bg-background/40 flex flex-col">
    <div class="px-4 py-3 border-b border-primary/10 flex items-center justify-between shrink-0">
      <h3 class="text-[10px] uppercase tracking-widest text-muted-foreground/70 font-medium">
        会话文件 · {{ files.length }}
      </h3>
      <div class="flex items-center gap-1">
        <button
          class="p-1 hover:bg-primary/10 rounded transition-colors"
          title="刷新"
          :disabled="isLoading || !conversationId"
          @click="refresh"
        >
          <svg class="w-3.5 h-3.5 text-muted-foreground/70" :class="isLoading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 1 1-9-9c2.5 0 4.8 1 6.5 2.7L21 8"/>
            <path d="M21 3v5h-5"/>
          </svg>
        </button>
        <button
          class="p-1 hover:bg-primary/10 rounded transition-colors"
          title="隐藏"
          @click="emit('close')"
        >
          <svg class="w-3.5 h-3.5 text-muted-foreground/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-2 py-2 space-y-1">
      <!-- 空态 -->
      <div v-if="!isLoading && files.length === 0" class="text-xs text-muted-foreground/60 text-center py-8 px-2">
        <div class="mb-2 text-2xl">📂</div>
        <div v-if="!conversationId">先选择会话</div>
        <div v-else-if="errorMsg" class="text-red-400">{{ errorMsg }}</div>
        <div v-else>本会话暂无文件操作<br/>(用 file 工具写入后会出现在这里)</div>
      </div>

      <!-- 加载中 -->
      <div v-if="isLoading && files.length === 0" class="text-xs text-muted-foreground/60 text-center py-8">
        加载中...
      </div>

      <!-- 文件卡片 -->
      <button
        v-for="file in files"
        :key="file.path + file.timestamp"
        :class="[
          'w-full text-left px-3 py-2 rounded-md text-xs border transition-colors',
          file.status === 'success'
            ? 'border-transparent hover:bg-primary/5 hover:border-primary/20'
            : 'border-red-500/30 bg-red-500/5'
        ]"
        :title="file.path"
        @click="emit('openViewer', file)"
      >
        <!-- 第一行: action 图标 + 文件名 + 大小 -->
        <div class="flex items-center gap-2 mb-1">
          <span class="text-sm shrink-0">{{ ACTION_META[file.action]?.icon || '📄' }}</span>
          <span :class="['text-[10px] font-medium shrink-0', ACTION_META[file.action]?.color || '']">
            {{ ACTION_META[file.action]?.label || file.action }}
          </span>
          <span class="flex-1 truncate font-mono text-foreground/90">{{ basename(file.path) }}</span>
          <span class="text-[10px] text-muted-foreground/60 shrink-0">{{ formatSize(file.size) }}</span>
        </div>
        <!-- 第二行: 父目录 + 时间 -->
        <div class="flex items-center gap-2 ml-6 text-[10px] text-muted-foreground/60">
          <span v-if="dirname(file.path)" class="truncate flex-1 font-mono">{{ dirname(file.path) }}/</span>
          <span v-else class="flex-1">/</span>
          <span class="shrink-0">{{ formatTime(file.timestamp) }}</span>
        </div>
        <!-- 错误信息 -->
        <div v-if="file.error" class="ml-6 mt-1 text-[10px] text-red-400 truncate">
          {{ file.error }}
        </div>
      </button>
    </div>
  </aside>
</template>
