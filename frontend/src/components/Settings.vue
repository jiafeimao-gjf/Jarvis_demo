<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useApi } from '@/composables/useApi'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const settingsStore = useSettingsStore()
const api = useApi()

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
    }
  }
  hardware: Record<string, number>
  storage: { memory_dir: string; logs_dir: string }
  log_level: string
}

interface OllamaModel {
  name: string
  model: string
  size?: number
  modified_at?: string
  provider?: string
}

const config = ref<Config | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)
const message = ref('')
const isLoadingModels = ref(false)
const ollamaModels = ref<OllamaModel[]>([])

// Form bound directly to settings store
const form = computed(() => settingsStore.settings)

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
      settingsStore.mergeFromBackend(config.value)
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

    // Sync to backend
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

    showMessage('配置已保存，将在刷新后生效', 'success')
  } catch (e) {
    showMessage('保存配置失败', 'error')
  } finally {
    isSaving.value = false
  }
}

function showMessage(msg: string, type: 'success' | 'error') {
  message.value = msg
  setTimeout(() => { message.value = '' }, 3000)
}

async function loadOllamaModels() {
  isLoadingModels.value = true
  try {
    const res = await fetch('/api/chat/models')
    if (res.ok) {
      const data = await res.json()
      ollamaModels.value = data.models || []
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
            <select class="w-full bg-background rounded px-3 py-2 border border-border">
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
            <label class="block text-sm mb-1">默认 Provider</label>
            <select
              v-model="form.ai_default_provider"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            >
              <option value="ollama">Ollama (本地)</option>
              <option value="openai">OpenAI (云)</option>
              <option value="anthropic">Anthropic (Claude)</option>
            </select>
          </div>

          <div>
            <label class="block text-sm mb-1">默认模型</label>
            <select
              v-model="form.ai_default_model"
              class="w-full bg-background rounded px-3 py-2 border border-border"
            >
              <option v-if="ollamaModels.length === 0" value="">请选择模型</option>
              <option v-for="m in ollamaModels" :key="m.name" :value="m.name">
                {{ m.name }}
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
          可用模型: qwen3:4b, qwen3:8b, qwen3-vl:4b, llama3:8b, gpt-4o-mini, claude-3-haiku
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
  min-height: 100vh;
}
</style>