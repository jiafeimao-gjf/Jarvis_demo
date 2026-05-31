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
  user_name: string
  work_folder: string
  persona_prompt: string
  abilities_prompt: string
  memory_prompt: string
  tools_prompt: string
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
  user_name: '',
  work_folder: '',
  persona_prompt: '',
  abilities_prompt: '',
  memory_prompt: '',
  tools_prompt: '',
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
  const isSyncing = ref(false)

  // Load from localStorage first (for offline use)
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        settings.value = { ...DEFAULT_SETTINGS, ...parsed }
      }
    } catch (e) {
      console.error('Failed to load settings from storage:', e)
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

  // Sync from backend DB
  async function syncFromBackend() {
    if (isSyncing.value) return
    isSyncing.value = true

    try {
      const res = await fetch('/api/memory/settings')
      if (res.ok) {
        const data = await res.json()
        const dbSettings = data.settings || {}

        // Merge DB settings into localStorage (DB takes precedence)
        for (const [key, value] of Object.entries(dbSettings)) {
          if (key in settings.value) {
            // For nested objects like hardware, deep merge
            if (typeof value === 'object' && value !== null) {
              (settings.value as Record<string, any>)[key] = {
                ...(settings.value as Record<string, any>)[key],
                ...(value as object)
              }
            } else {
              (settings.value as any)[key] = value
            }
          }
        }

        // Save merged result to localStorage
        saveToStorage()
      }
    } catch (e) {
      console.error('Failed to sync settings from backend:', e)
    } finally {
      isSyncing.value = false
      isLoaded.value = true
    }
  }

  // Save a single setting to backend
  async function saveSettingToBackend(key: string, value: any) {
    try {
      await fetch(`/api/memory/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value)
      })
    } catch (e) {
      console.error('Failed to save setting to backend:', e)
    }
  }

  // Watch for changes and persist
  watch(settings, () => {
    saveToStorage()
  }, { deep: true })

  // Update a single setting (local + backend)
  async function updateSetting<K extends keyof Settings>(key: K, value: Settings[K]) {
    settings.value[key] = value
    // Save to backend DB
    await saveSettingToBackend(key, value)
  }

  // Merge config from backend API (initial load)
  function mergeFromApi(config: Record<string, any>) {
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
    isSyncing,
    loadFromStorage,
    saveToStorage,
    syncFromBackend,
    updateSetting,
    mergeFromApi
  }
})