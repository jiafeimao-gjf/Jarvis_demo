<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import ProviderManager from './ProviderManager.vue'
import VoiceClonePanel from './VoiceClonePanel.vue'
import SkillManager from './SkillManager.vue'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const settingsStore = useSettingsStore()

interface Config {
  app_name: string
  app_version: string
  server: { host: string; port: number; debug: boolean; reload: boolean }
  ai: {
    default_provider: string
    default_model: string
    enable_fallback: boolean
    fallback_chain: string[]
    providers: {
      ollama: { base_url: string; model: string; vision_model: string }
      openai: { configured: boolean }
      anthropic: { configured: boolean }
    }
  }
  hardware: Record<string, number>
  storage: { memory_dir: string; logs_dir: string }
  log_level: string
}

interface ModelOption {
  name: string
  provider: string
}

const config = ref<Config | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)
const message = ref('')
const isLoadingModels = ref(false)

// Models — Ollama loaded from API, cloud providers hardcoded reference
const providerModels = ref<Record<string, ModelOption[]>>({
  ollama: [],
  openai: [
    { name: 'gpt-4o-mini', provider: 'openai' },
    { name: 'gpt-4o', provider: 'openai' },
  ],
  anthropic: [
    { name: 'claude-3-haiku', provider: 'anthropic' },
    { name: 'claude-3-5-sonnet', provider: 'anthropic' },
  ],
})

// Form bound directly to settings store
const form = computed(() => settingsStore.settings)

// Current models based on selected provider
const availableModels = computed(() => {
  const provider = form.value.ai_default_provider
  return providerModels.value[provider] || []
})

// ── Section navigation ──────────────────────────────────────────────────────
// Each section: { id, label, icon (SVG path data), description }
interface SectionDef {
  id: string
  label: string
  desc: string
  icon: string  // SVG inner content (path d="..." etc.)
}

const sections: SectionDef[] = [
  { id: 'server', label: '服务器', desc: '端口 / 日志级别',
    icon: 'M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01' },
  { id: 'ai', label: 'AI', desc: '默认 Provider / 模型 / 故障转移',
    icon: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
  { id: 'prompt', label: 'Prompt', desc: '角色 / 能力 / 记忆 / 工具 / 工作目录',
    icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
  { id: 'ollama', label: 'Ollama', desc: '本地 Ollama 服务器 / 模型',
    icon: 'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z' },
  { id: 'provider', label: 'Provider', desc: '多 Provider 实例管理 (CRUD)',
    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4' },
  { id: 'skill', label: '技能', desc: 'Skill 管理 (启用 / 标签 / 分组)',
    icon: 'M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z' },
  { id: 'voice', label: '声音', desc: 'F5-TTS 声音克隆 + 全局 TTS 开关',
    icon: 'M19 11a7 7 0 01-14 0M12 18v3m-4 0h8M12 14a4 4 0 01-4-4V6a4 4 0 118 0v4a4 4 0 01-4 4z' },
  { id: 'hardware', label: '硬件', desc: '摄像头 / 麦克风参数',
    icon: 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z' },
  { id: 'storage', label: '存储', desc: '记忆 / 日志目录',
    icon: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4' },
]

const activeSection = ref<string>('server')

// Scroll content pane to top when switching
function switchSection(id: string) {
  activeSection.value = id
  // Scroll right pane to top
  const pane = document.getElementById('settings-content-pane')
  if (pane) pane.scrollTop = 0
}

// Watch provider change to reset model if not available for new provider
watch(() => form.value.ai_default_provider, (newProvider, oldProvider) => {
  if (oldProvider && newProvider !== oldProvider) {
    const currentModel = form.value.ai_default_model
    const validModels = providerModels.value[newProvider] || []
    const modelExists = validModels.some(m => m.name === currentModel)
    if (!modelExists && validModels.length > 0) {
      form.value.ai_default_model = validModels[0].name
    }
  }
})

onMounted(async () => {
  // Wait for settings to load from localStorage
  if (!settingsStore.isLoaded) {
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  // Sync from backend DB
  await settingsStore.syncFromBackend()
  // Then load from /api/config for server-side settings
  await loadConfig()
  await loadOllamaModels()
})

async function loadConfig() {
  isLoading.value = true
  try {
    const res = await fetch('/api/config')
    if (res.ok) {
      config.value = await res.json()
      // Merge backend config into localStorage (won't override local changes)
      if (config.value) { settingsStore.mergeFromApi(config.value) }
    }
  } catch (e) {
    showMessage('加载配置失败', 'error')
  } finally {
    isLoading.value = false
  }
}

async function saveConfig() {
  isSaving.value = true
  message.value = ''

  try {
    settingsStore.saveToStorage()

    const results = await Promise.allSettled([
      // Runtime config
      fetch(`/api/config?key=server.port&value=${form.value.server_port}`, { method: 'PUT' }),
      fetch(`/api/config?key=ai.default_provider&value=${form.value.ai_default_provider}`, { method: 'PUT' }),
      fetch(`/api/config?key=ai.default_model&value=${form.value.ai_default_model}`, { method: 'PUT' }),
      fetch(`/api/config?key=ai.enable_fallback&value=${form.value.ai_enable_fallback}`, { method: 'PUT' }),
      // Prompt & hardware → memory DB
      fetch('/api/memory/settings/persona_prompt', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.persona_prompt)
      }),
      fetch('/api/memory/settings/abilities_prompt', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.abilities_prompt)
      }),
      fetch('/api/memory/settings/memory_prompt', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.memory_prompt)
      }),
      fetch('/api/memory/settings/tools_prompt', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.tools_prompt)
      }),
      fetch('/api/memory/settings/work_folder', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.work_folder)
      }),
      fetch('/api/memory/settings/hardware', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value.hardware)
      }),
    ])

    const failures = results.filter(r => r.status === 'rejected').length
    if (failures > 0) {
      showMessage(`已本地保存，${failures} 项后台同步失败`, 'error')
    } else {
      showMessage('配置已保存', 'success')
    }
  } catch (e) {
    showMessage('保存配置失败', 'error')
  } finally {
    isSaving.value = false
  }
}

function showMessage(msg: string, _type: 'success' | 'error') {
  message.value = msg
  setTimeout(() => { message.value = '' }, 3000)
}

async function loadOllamaModels() {
  isLoadingModels.value = true
  try {
    const res = await fetch('/api/chat/models')
    if (res.ok) {
      const data = await res.json()
      // Update ollama models from backend
      providerModels.value.ollama = (data.models || []).map((m: any) => ({
        name: m.name || m.model,
        provider: 'ollama'
      }))
    }
  } catch (e) {
    console.error('Failed to load models:', e)
  } finally {
    isLoadingModels.value = false
  }
}
</script>

<template>
  <div class="settings-page flex flex-col h-screen bg-background">
    <!-- ═══════════ Sticky Header ═══════════ -->
    <header class="flex items-center gap-3 px-4 sm:px-6 py-3 border-b border-border bg-background/95 backdrop-blur sticky top-0 z-10">
      <button
        class="p-2 hover:bg-accent rounded-lg transition-colors flex-shrink-0"
        @click="emit('close')"
        title="返回"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <h1 class="text-lg sm:text-xl font-bold flex-1 truncate">系统设置</h1>
      <button
        class="px-3 sm:px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 text-sm flex-shrink-0 disabled:opacity-50"
        :disabled="isSaving"
        @click="saveConfig"
      >
        {{ isSaving ? '保存中...' : '保存' }}
      </button>
    </header>

    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
      <div class="animate-spin w-8 h-8 border-4 border-primary border-t-transparent rounded-full"></div>
    </div>

    <div v-else-if="config" class="flex-1 flex overflow-hidden">
      <!-- ═══════════ Left Sidebar (desktop) / Top Tabs (mobile) ═══════════ -->
      <nav class="settings-sidebar hidden md:flex flex-col w-52 flex-shrink-0 border-r border-border bg-secondary/30 overflow-y-auto py-2">
        <button
          v-for="s in sections"
          :key="s.id"
          class="sidebar-item group flex items-start gap-3 px-4 py-3 mx-2 rounded-lg text-left transition-colors"
          :class="activeSection === s.id
            ? 'bg-primary/15 text-primary border-l-2 border-primary'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground border-l-2 border-transparent'"
          @click="switchSection(s.id)"
        >
          <svg class="w-5 h-5 mt-0.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path :d="s.icon"/>
          </svg>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium">{{ s.label }}</div>
            <div class="text-xs text-muted-foreground mt-0.5 truncate">{{ s.desc }}</div>
          </div>
        </button>
      </nav>

      <!-- Mobile: horizontal scroll tabs -->
      <nav class="md:hidden flex overflow-x-auto border-b border-border bg-secondary/30 px-2 py-1 gap-1 flex-shrink-0">
        <button
          v-for="s in sections"
          :key="s.id"
          class="flex-shrink-0 px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors"
          :class="activeSection === s.id
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-accent'"
          @click="switchSection(s.id)"
        >
          {{ s.label }}
        </button>
      </nav>

      <!-- ═══════════ Right Content Pane ═══════════ -->
      <main id="settings-content-pane" class="flex-1 overflow-y-auto px-4 sm:px-8 py-6">
        <!-- 服务器 -->
        <section v-show="activeSection === 'server'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">服务器配置</h2>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm mb-1">端口</label>
              <input
                v-model="form.server_port"
                type="number"
                class="w-full bg-background rounded px-3 py-2 border border-border"
              />
            </div>
            <div>
              <label class="block text-sm mb-1">日志级别</label>
              <select v-model="form.log_level" class="w-full bg-background rounded px-3 py-2 border border-border">
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
          </div>
        </section>

        <!-- AI -->
        <section v-show="activeSection === 'ai'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">AI 配置</h2>
          <div class="space-y-4">
            <div>
              <label class="block text-sm mb-1">用户名</label>
              <input
                v-model="form.user_name"
                type="text"
                class="w-full bg-background rounded px-3 py-2 border border-border"
                placeholder="设置用户名用于区分对话"
              />
            </div>
            <div>
              <label class="block text-sm mb-1">默认 Provider</label>
              <select
                v-model="form.ai_default_provider"
                class="w-full bg-background rounded px-3 py-2 border border-border"
              >
                <option value="ollama">Ollama (本地)</option>
                <option value="openai">OpenAI (云端)</option>
                <option value="anthropic">Anthropic Claude (云端)</option>
              </select>
            </div>
            <div>
              <label class="block text-sm mb-1">默认模型</label>
              <select
                v-model="form.ai_default_model"
                class="w-full bg-background rounded px-3 py-2 border border-border"
              >
                <option v-if="availableModels.length === 0" value="">请选择模型</option>
                <option v-for="m in availableModels" :key="m.name" :value="m.name">
                  {{ m.name }} ({{ m.provider }})
                </option>
              </select>
            </div>
            <div class="flex items-center gap-2">
              <input
                v-model="form.ai_enable_fallback"
                type="checkbox"
                id="fallback"
                class="w-4 h-4"
              />
              <label for="fallback">启用故障自动转移</label>
            </div>
          </div>
        </section>

        <!-- Prompt -->
        <section v-show="activeSection === 'prompt'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">Prompt 设置</h2>
          <div class="space-y-4">
            <div>
              <label class="block text-sm mb-1">角色设定</label>
              <textarea
                v-model="form.persona_prompt"
                rows="3"
                class="w-full bg-background rounded px-3 py-2 border border-border resize-none"
                placeholder="定义 AI 的角色和身份，例如：你是贾维斯，一个智能助手..."
              />
            </div>
            <div>
              <label class="block text-sm mb-1">能力说明</label>
              <textarea
                v-model="form.abilities_prompt"
                rows="3"
                class="w-full bg-background rounded px-3 py-2 border border-border resize-none"
                placeholder="描述 AI 能做什么，例如：可以帮助用户处理文件、回答问题..."
              />
            </div>
            <div>
              <label class="block text-sm mb-1">记忆说明</label>
              <textarea
                v-model="form.memory_prompt"
                rows="2"
                class="w-full bg-background rounded px-3 py-2 border border-border resize-none"
                placeholder="关于记忆系统的说明，例如：会记住用户的偏好和历史对话..."
              />
            </div>
            <div>
              <label class="block text-sm mb-1">工具说明</label>
              <textarea
                v-model="form.tools_prompt"
                rows="2"
                class="w-full bg-background rounded px-3 py-2 border border-border resize-none"
                placeholder="关于可用工具的补充说明..."
              />
            </div>
            <div>
              <label class="block text-sm mb-1">工作目录</label>
              <input
                v-model="form.work_folder"
                type="text"
                class="w-full bg-background rounded px-3 py-2 border border-border"
                placeholder="设置 AI 的工作目录，默认为当前目录"
              />
            </div>
          </div>
        </section>

        <!-- Ollama -->
        <section v-show="activeSection === 'ollama'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">Ollama 配置</h2>
          <div class="space-y-4">
            <div>
              <label class="block text-sm mb-1">服务器地址</label>
              <input
                v-model="form.ollama_base_url"
                type="text"
                class="w-full bg-background rounded px-3 py-2 border border-border"
                placeholder="http://localhost:11434"
              />
            </div>
            <div>
              <label class="block text-sm mb-1">默认模型</label>
              <select
                v-model="form.ollama_model"
                class="w-full bg-background rounded px-3 py-2 border border-border"
              >
                <option v-if="isLoadingModels" value="" disabled>加载中...</option>
                <option v-else-if="providerModels.ollama.length === 0" value="">无可用模型</option>
                <option v-for="m in providerModels.ollama" :key="m.name" :value="m.name">
                  {{ m.name }}
                </option>
              </select>
              <button
                class="mt-2 text-sm text-primary hover:underline"
                @click="loadOllamaModels"
                :disabled="isLoadingModels"
              >
                {{ isLoadingModels ? '刷新中...' : '刷新模型列表' }}
              </button>
            </div>
          </div>
          <div class="mt-4 text-sm text-muted-foreground">
            Ollama 模型从 API 动态加载 | 云端: gpt-4o-mini, gpt-4o, claude-3-haiku, claude-3-5-sonnet
          </div>
        </section>

        <!-- Provider -->
        <section v-show="activeSection === 'provider'" class="bg-secondary rounded-lg p-6 max-w-4xl">
          <h2 class="text-lg font-semibold mb-4">Provider 管理</h2>
          <ProviderManager />
        </section>

        <!-- 技能 -->
        <section v-show="activeSection === 'skill'" class="bg-secondary rounded-lg p-6 max-w-4xl">
          <h2 class="text-lg font-semibold mb-4">技能管理</h2>
          <SkillManager />
        </section>

        <!-- 声音 -->
        <section v-show="activeSection === 'voice'" class="bg-secondary rounded-lg p-6 max-w-4xl">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-lg font-semibold">声音克隆 (F5-TTS)</h2>
            <label class="flex items-center gap-2 cursor-pointer" :title="settingsStore.settings.tts_enabled ? '点击关闭全局 TTS (聊天不再朗读, 单条喇叭也禁用)' : '点击启用全局 TTS'">
              <span class="text-xs text-muted-foreground">全局 TTS</span>
              <span
                class="w-9 h-5 rounded-full flex-shrink-0 transition-colors"
                :class="settingsStore.settings.tts_enabled ? 'bg-green-500' : 'bg-gray-600'"
                @click="settingsStore.updateSetting('tts_enabled', !settingsStore.settings.tts_enabled)"
              >
                <span
                  class="block w-3.5 h-3.5 rounded-full bg-white transform transition-transform mt-[3px]"
                  :class="settingsStore.settings.tts_enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'"
                />
              </span>
              <span class="text-xs" :class="settingsStore.settings.tts_enabled ? 'text-green-400' : 'text-gray-500'">
                {{ settingsStore.settings.tts_enabled ? '开' : '关' }}
              </span>
            </label>
          </div>
          <p v-if="!settingsStore.settings.tts_enabled" class="text-xs text-muted-foreground mb-3 px-2 py-1.5 bg-yellow-500/10 text-yellow-400 rounded">
            ⚠️ TTS 已关闭 — 聊天回复不再朗读, 单条消息的 🔈 喇叭按钮也已禁用 (声音克隆配置仍可调整)
          </p>
          <VoiceClonePanel />
        </section>

        <!-- 硬件 -->
        <section v-show="activeSection === 'hardware'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">硬件配置</h2>
          <div class="grid grid-cols-3 gap-4">
            <div>
              <label class="block text-sm mb-1">摄像头 ID</label>
              <input v-model="form.hardware.camera_device_id" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
            <div>
              <label class="block text-sm mb-1">分辨率宽度</label>
              <input v-model="form.hardware.camera_width" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
            <div>
              <label class="block text-sm mb-1">分辨率高度</label>
              <input v-model="form.hardware.camera_height" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
            <div>
              <label class="block text-sm mb-1">帧率</label>
              <input v-model="form.hardware.camera_fps" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
            <div>
              <label class="block text-sm mb-1">采样率</label>
              <input v-model="form.hardware.microphone_sample_rate" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
            <div>
              <label class="block text-sm mb-1">声道数</label>
              <input v-model="form.hardware.audio_channels" type="number" class="w-full bg-background rounded px-3 py-2 border border-border" />
            </div>
          </div>
        </section>

        <!-- 存储 -->
        <section v-show="activeSection === 'storage'" class="bg-secondary rounded-lg p-6 max-w-3xl">
          <h2 class="text-lg font-semibold mb-4">存储配置</h2>
          <div class="space-y-2 text-sm text-muted-foreground">
            <div>记忆目录: {{ config.storage.memory_dir }}</div>
            <div>日志目录: {{ config.storage.logs_dir }}</div>
          </div>
        </section>

        <!-- Toast -->
        <div
          v-if="message"
          class="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg text-sm shadow-lg"
          :class="message.includes('失败') ? 'bg-destructive/20 text-destructive' : 'bg-green-500/20 text-green-500'"
        >
          {{ message }}
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  background: var(--background);
}

/* Sidebar item hover animation */
.sidebar-item {
  border-left-width: 2px;
}
</style>
