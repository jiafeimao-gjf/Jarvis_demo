<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'

// 按需注册常用语言 — 包体可控, 启动快
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import bash from 'highlight.js/lib/languages/bash'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import markdown from 'highlight.js/lib/languages/markdown'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'

hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('scss', css)
hljs.registerLanguage('less', css)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('java', java)

// 引入 GitHub Dark 主题 — 与 cyber 风 UI 协调
import 'highlight.js/styles/github-dark.css'

import { useApi } from '@/composables/useApi'
import type { FileOp } from '@/types'

const props = defineProps<{
  conversationId: string | null
  file: FileOp | null
}>()

const emit = defineEmits<{ close: [] }>()

const api = useApi()

const content = ref<string>('')
const encoding = ref<'utf-8' | 'base64'>('utf-8')
const size = ref(0)
const ext = ref('')
const truncated = ref(false)
const notFound = ref(false)
const errorMsg = ref<string | null>(null)
const isLoading = ref(false)

const EXT_LANG: Record<string, string> = {
  '.py': 'python', '.js': 'javascript', '.jsx': 'javascript',
  '.ts': 'typescript', '.tsx': 'typescript',
  '.json': 'json',
  '.yaml': 'yaml', '.yml': 'yaml',
  '.sh': 'bash', '.bash': 'bash',
  '.html': 'html', '.htm': 'html', '.xml': 'xml', '.svg': 'xml', '.vue': 'xml',
  '.css': 'css', '.scss': 'css', '.less': 'css',
  '.md': 'markdown', '.markdown': 'markdown',
  '.go': 'go', '.rs': 'rust', '.java': 'java',
}

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'])

// 渲染模式: 'code' | 'markdown' | 'html' | 'image' | 'text' | 'binary' | 'too-large' | 'empty'
const mode = computed(() => {
  if (!props.file) return 'empty'
  if (notFound.value) return 'empty'
  if (truncated.value) return 'too-large'
  if (errorMsg.value) return 'empty'
  if (!content.value) return 'empty'
  if (IMAGE_EXTS.has(ext.value)) return 'image'
  if (ext.value === '.md' || ext.value === '.markdown') return 'markdown'
  if (ext.value === '.html' || ext.value === '.htm') return 'html'
  if (encoding.value === 'base64') return 'binary'
  // 代码 vs 纯文本: 有对应语言就用 code, 否则 text
  if (EXT_LANG[ext.value]) return 'code'
  return 'text'
})

// 渲染 Markdown
const renderedMarkdown = computed(() => {
  if (mode.value !== 'markdown') return ''
  try {
    const raw = marked.parse(content.value) as string
    return DOMPurify.sanitize(raw, {
      ALLOWED_TAGS: ['p','br','strong','em','del','s','code','pre','ul','ol','li','blockquote','a','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td','hr','img','span','div'],
      ALLOWED_ATTR: ['href','target','src','alt','class','id'],
    })
  } catch {
    return ''
  }
})

// 渲染代码高亮
const highlightedCode = computed(() => {
  if (mode.value !== 'code') return ''
  const lang = EXT_LANG[ext.value]
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(content.value, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(content.value).value
  } catch {
    // fallback: 转义 HTML
    return content.value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }
})

const htmlSrcDoc = computed(() => {
  if (mode.value !== 'html') return ''
  return content.value
})

const imageDataUrl = computed(() => {
  if (mode.value !== 'image') return ''
  // content 是 base64 编码的二进制
  if (encoding.value !== 'base64') return ''
  const mimeMap: Record<string, string> = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
  }
  const mime = mimeMap[ext.value] || 'image/png'
  return `data:${mime};base64,${content.value}`
})

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

// 监听 file 变化, 加载内容
watch(
  () => props.file,
  async (f) => {
    if (!f || !props.conversationId) {
      content.value = ''
      return
    }
    isLoading.value = true
    errorMsg.value = null
    notFound.value = false
    truncated.value = false
    try {
      const data = await api.getFileContent(props.conversationId, f.path)
      content.value = data.content
      encoding.value = data.encoding
      size.value = data.size
      ext.value = data.extension
      truncated.value = data.truncated
      if (data.message) errorMsg.value = data.message
    } catch (e) {
      const msg = (e as Error).message
      if (msg.includes('404') || msg.includes('文件已不存在')) {
        notFound.value = true
      } else {
        errorMsg.value = msg
      }
      content.value = ''
    } finally {
      isLoading.value = false
    }
  },
  { immediate: true }
)

// ESC 关闭
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

import { onMounted } from 'vue'
onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

function downloadFile() {
  if (!props.file || !content.value) return
  const blob = encoding.value === 'base64'
    ? base64ToBlob(content.value)
    : new Blob([content.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = basename(props.file.path)
  a.click()
  URL.revokeObjectURL(url)
}

function base64ToBlob(b64: string): Blob {
  const bytes = atob(b64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  // 根据 ext 推断 mime
  const mimeMap: Record<string, string> = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.pdf': 'application/pdf',
  }
  const mime = mimeMap[ext.value] || 'application/octet-stream'
  return new Blob([arr], { type: mime })
}

function basename(path: string): string {
  return path.split(/[/\\]/).pop() || path
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="file"
      class="fixed inset-0 z-[110] bg-black/80 flex flex-col"
      @click.self="emit('close')"
    >
      <!-- 顶栏 -->
      <div class="flex items-center justify-between px-4 py-2 bg-background/95 border-b border-primary/20 shrink-0">
        <div class="flex items-center gap-3 min-w-0 flex-1">
          <span class="text-sm font-medium text-foreground truncate" :title="file.path">
            {{ file.path }}
          </span>
          <span class="text-[10px] text-muted-foreground/60 shrink-0">
            {{ formatSize(size) }}
          </span>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button
            class="w-8 h-8 rounded-md hover:bg-primary/10 text-foreground/70 hover:text-primary flex items-center justify-center transition-colors"
            title="下载"
            @click="downloadFile"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
            </svg>
          </button>
          <button
            class="w-8 h-8 rounded-md hover:bg-primary/10 text-foreground/70 hover:text-primary flex items-center justify-center transition-colors"
            title="关闭 (Esc)"
            @click="emit('close')"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="flex-1 overflow-auto bg-background">
        <!-- 加载中 -->
        <div v-if="isLoading" class="flex items-center justify-center h-full text-muted-foreground">
          加载中...
        </div>

        <!-- 错误 / 文件不存在 -->
        <div v-else-if="notFound" class="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <div class="text-3xl">📄</div>
          <div>文件已不存在</div>
          <div class="text-xs text-muted-foreground/60">{{ file.path }} 可能被外部删除或移动</div>
        </div>

        <div v-else-if="errorMsg" class="p-6 text-red-400 text-sm">
          {{ errorMsg }}
        </div>

        <!-- 太大 -->
        <div v-else-if="mode === 'too-large'" class="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <div class="text-3xl">📦</div>
          <div>文件过大 ({{ formatSize(size) }}), 不在线预览</div>
          <button class="mt-2 px-3 py-1 text-xs rounded bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30" @click="downloadFile">
            下载查看
          </button>
        </div>

        <!-- 图片 -->
        <div v-else-if="mode === 'image'" class="flex items-center justify-center h-full p-4">
          <img :src="imageDataUrl" :alt="file.path" class="max-w-full max-h-full object-contain" />
        </div>

        <!-- HTML (sandboxed iframe) -->
        <iframe
          v-else-if="mode === 'html'"
          :srcdoc="htmlSrcDoc"
          sandbox="allow-same-origin"
          class="w-full h-full bg-white"
        />

        <!-- Markdown -->
        <div
          v-else-if="mode === 'markdown'"
          class="markdown-content p-6 max-w-4xl mx-auto text-sm leading-relaxed"
          v-html="renderedMarkdown"
        />

        <!-- 代码 (highlight.js) -->
        <pre
          v-else-if="mode === 'code'"
          class="hljs-container p-4 text-xs leading-relaxed"
        ><code class="hljs" v-html="highlightedCode"></code></pre>

        <!-- 纯文本 -->
        <pre
          v-else-if="mode === 'text'"
          class="p-4 text-xs leading-relaxed font-mono whitespace-pre-wrap break-all text-foreground/90"
        >{{ content }}</pre>

        <!-- 二进制 (非图片) -->
        <div v-else-if="mode === 'binary'" class="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <div class="text-3xl">💾</div>
          <div>二进制文件, 不在线预览</div>
          <button class="mt-2 px-3 py-1 text-xs rounded bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30" @click="downloadFile">
            下载查看
          </button>
        </div>

        <!-- 空内容 -->
        <div v-else class="flex items-center justify-center h-full text-muted-foreground text-sm">
          (空文件)
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.hljs-container {
  background: #0d1117;  /* github-dark 背景色, 与主题协调 */
  min-height: 100%;
}

/* 代码块横向滚动 */
.hljs-container code {
  display: block;
  white-space: pre;
  overflow-x: auto;
}

/* markdown 渲染区基础样式 (与 ChatMessage 一致) */
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
  background: hsl(var(--muted));
  padding: 0.15em 0.4em;
  border-radius: 0.25rem;
  font-size: 0.875em;
}
.markdown-content :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}
.markdown-content :deep(blockquote) {
  border-left: 3px solid hsl(var(--primary) / 0.5);
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  color: hsl(var(--foreground));
  font-weight: 600;
  margin: 0.75rem 0 0.5rem;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 1.5rem;
  margin: 0.5rem 0;
}
</style>
