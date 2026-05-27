import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const STORAGE_KEY = 'jarvis_settings'

export interface Settings {
  server_port: number
  ai_default_provider: string
  ai_default_model: string
  ai_enable_fallback: boolean
  ollama_base_url: string
  ollama_model: string
  log_level: string
  hardware: {
    camera_device_id: number
    camera_width: number
    camera_height: number
    camera_fps: number
    microphone_sample_rate: number
    audio_channels: number
  }
}

const DEFAULT_SETTINGS: Settings = {
  server_port: 9529,
  ai_default_provider: 'ollama',
  ai_default_model: 'qwen3:4b',
  ai_enable_fallback: true,
  ollama_base_url: 'http://localhost:11434',
  ollama_model: '',
  log_level: 'INFO',
  hardware: {
    camera_device_id: 0,
    camera_width: 1280,
    camera_height: 720,
    camera_fps: 30,
    microphone_sample_rate: 16000,
    audio_channels: 1
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<Settings>({ ...DEFAULT_SETTINGS })
  const isLoaded = ref(false)

  // Load from localStorage
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        settings.value = { ...DEFAULT_SETTINGS, ...parsed }
      }
      isLoaded.value = true
    } catch (e) {
      console.error('Failed to load settings from storage:', e)
      isLoaded.value = true
    }
  }

  // Save to localStorage
  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings.value))
    } catch (e) {
      console.error('Failed to save settings to storage:', e)
    }
  }

  // Watch for changes and persist
  watch(settings, () => {
    saveToStorage()
  }, { deep: true })

  // Update a single setting
  function updateSetting<K extends keyof Settings>(key: K, value: Settings[K]) {
    settings.value[key] = value
  }

  // Merge config from backend
  function mergeFromBackend(config: Record<string, any>) {
    if (config.server?.port) {
      settings.value.server_port = config.server.port
    }
    if (config.ai?.default_provider) {
      settings.value.ai_default_provider = config.ai.default_provider
    }
    if (config.ai?.default_model) {
      settings.value.ai_default_model = config.ai.default_model
    }
    if (config.ai?.enable_fallback !== undefined) {
      settings.value.ai_enable_fallback = config.ai.enable_fallback
    }
    if (config.ai?.providers?.ollama) {
      if (config.ai.providers.ollama.base_url) {
        settings.value.ollama_base_url = config.ai.providers.ollama.base_url
      }
      if (config.ai.providers.ollama.model) {
        settings.value.ollama_model = config.ai.providers.ollama.model
      }
    }
    if (config.log_level) {
      settings.value.log_level = config.log_level
    }
    if (config.hardware) {
      settings.value.hardware = { ...settings.value.hardware, ...config.hardware }
    }
  }

  // Initialize
  loadFromStorage()

  return {
    settings,
    isLoaded,
    loadFromStorage,
    saveToStorage,
    updateSetting,
    mergeFromBackend
  }
})