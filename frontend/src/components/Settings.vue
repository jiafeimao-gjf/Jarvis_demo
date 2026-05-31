<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useSettingsStore } from '@/stores/settings'

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
      openai: { has_api_key: boolean }
      anthropic: { has_api_key: boolean }
      minimax: { has_api_key: boolean }
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
const ollamaModels = ref<ModelOption[]>([])

// Predefined models for each provider
const providerModels: Record<string, ModelOption[]> = {
  ollama: [
    { name: 'qwen3:4b', provider: 'ollama' },
    { name: 'qwen3:8b', provider: 'ollama' },
    { name: 'qwen3.5:9b-q8_0', provider: 'ollama' },
    { name: 'llama3:8b', provider: 'ollama' },
  ],
  openai: [
    { name: 'gpt-4o-mini', provider: 'openai' },
    { name: 'gpt-4o', provider: 'openai' },
  ],
  anthropic: [
    { name: 'claude-3-haiku', provider: 'anthropic' },
    { name: 'claude-3-sonnet', provider: 'anthropic' },
    { name: 'claude-3-5-sonnet', provider: 'anthropic' },
  ],
  minimax: [
    { name: 'MiniMax-M2.7', provider: 'minimax' },
  ]
}

// Form bound directly to settings store
const form = computed(() => settingsStore.settings)

// Current models based on selected provider
const availableModels = computed(() => {
  const provider = form.value.ai_default_provider
  return providerModels[provider] || []
})

// Watch provider change to reset model if not available for new provider
watch(() => form.value.ai_default_provider, (newProvider, oldProvider) => {
  if (oldProvider && newProvider !== oldProvider) {
    const currentModel = form.value.ai_default_model
    const validModels = providerModels[newProvider] || []
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
    // Save to localStorage (already done by watch, but explicit save for clarity)
    settingsStore.saveToStorage()

    // Sync to backend config (runtime settings)
    await fetch('/api/config?key=server.port&value=' + form.value.server_port, {
      method: 'PUT'
    })

    await fetch('/api/config?key=ai.default_provider&value=' + form.value.ai_default_provider, {
      method: 'PUT'
    })

    await fetch('/api/config?key=ai.default_model&value=' + form.value.ai_default_model, {
      method: 'PUT'
    })

    await fetch('/api/config?key=ai.enable_fallback&value=' + form.value.ai_enable_fallback, {
      method: 'PUT'
    })

    // Save prompt settings to memory DB
    await fetch('/api/memory/settings/persona_prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value.persona_prompt)
    })

    await fetch('/api/memory/settings/abilities_prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value.abilities_prompt)
    })

    await fetch('/api/memory/settings/memory_prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value.memory_prompt)
    })

    await fetch('/api/memory/settings/tools_prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value.tools_prompt)
    })

    await fetch('/api/memory/settings/work_folder', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value.work_folder)
    })

    showMessage('配置已保存', 'success')
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
      providerModels.ollama = (data.models || []).map((m: any) => ({
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
  <div class="settings-page p-6 max-w-4xl mx-auto">
    <div class="flex items-center gap-4 mb-6">
      <button
        class="p-2 hover:bg-accent rounded-lg transition-colors"
        @click="emit('close')"
        title="返回"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <h1 class="text-2xl font-bold">系统设置</h1>
    </div>

    <div v-if="isLoading" class="text-center py-8">
      <div class="animate-spin w-8 h-8 border-4 border-primary border-t-transparent rounded-full mx-auto"></div>
    </div>

    <div v-else-if="config" class="space-y-6">
      <!-- 服务器配置 -->
      <section class="bg-secondary rounded-lg p-4">
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

      <!-- AI 配置 -->
      <section class="bg-secondary rounded-lg p-4">
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
              <option value="openai">OpenAI (云)</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="minimax">MiniMax</option>
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

      <!-- Prompt 设置 -->
      <section class="bg-secondary rounded-lg p-4">
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

      <!-- Ollama 配置 -->
      <section class="bg-secondary rounded-lg p-4">
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
              <option v-else-if="ollamaModels.length === 0" value="">无可用模型</option>
              <option v-for="m in ollamaModels" :key="m.name" :value="m.name">
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
          可用模型: qwen3:4b, qwen3:8b, qwen3.5:9b-q8_0, llama3:8b, whisper-large-v2, gpt-4o-mini, claude-3-haiku
        </div>
      </section>

      <!-- 硬件配置 -->
      <section class="bg-secondary rounded-lg p-4">
        <h2 class="text-lg font-semibold mb-4">硬件配置</h2>

        <div class="grid grid-cols-3 gap-4">
          <div>
            <label class="block text-sm mb-1">摄像头 ID</label>
            <input
              v-model="form.hardware.camera_device_id"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
          <div>
            <label class="block text-sm mb-1">分辨率宽度</label>
            <input
              v-model="form.hardware.camera_width"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
          <div>
            <label class="block text-sm mb-1">分辨率高度</label>
            <input
              v-model="form.hardware.camera_height"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
          <div>
            <label class="block text-sm mb-1">帧率</label>
            <input
              v-model="form.hardware.camera_fps"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
          <div>
            <label class="block text-sm mb-1">采样率</label>
            <input
              v-model="form.hardware.microphone_sample_rate"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
          <div>
            <label class="block text-sm mb-1">声道数</label>
            <input
              v-model="form.hardware.audio_channels"
              type="number"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            />
          </div>
        </div>
      </section>

      <!-- 存储路径 -->
      <section class="bg-secondary rounded-lg p-4">
        <h2 class="text-lg font-semibold mb-4">存储配置</h2>
        <div class="space-y-2 text-sm text-muted-foreground">
          <div>记忆目录: {{ config.storage.memory_dir }}</div>
          <div>日志目录: {{ config.storage.logs_dir }}</div>
        </div>
      </section>

      <!-- 消息 -->
      <div
        v-if="message"
        :class="['px-4 py-2 rounded-lg text-sm', message.includes('失败') ? 'bg-destructive/20 text-destructive' : 'bg-green-500/20 text-green-500']"
      >
        {{ message }}
      </div>

      <!-- 保存按钮 -->
      <div class="flex justify-end gap-4">
        <button
          class="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90"
          :disabled="isSaving"
          @click="saveConfig"
        >
          {{ isSaving ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  background: var(--background);
  height: 100vh;
  overflow-y: auto;
}
</style>