import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ProviderInstance } from '@/types'

const STORAGE_KEY = 'jarvis_providers'

export const useProvidersStore = defineStore('providers', () => {
  const instances = ref<ProviderInstance[]>([])
  const activeProviderId = ref<string | null>(null)
  const isLoading = ref(false)
  const isSyncing = ref(false)

  // ── Persistence ─────────────────────────────────────────────────────────────

  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        instances.value = parsed.instances || []
        activeProviderId.value = parsed.activeProviderId || null
      }
    } catch (e) {
      console.error('[Providers] Failed to load from storage:', e)
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        instances: instances.value,
        activeProviderId: activeProviderId.value,
      }))
    } catch (e) {
      console.error('[Providers] Failed to save to storage:', e)
    }
  }

  // ── Backend sync ────────────────────────────────────────────────────────────

  async function loadFromBackend() {
    if (isLoading.value) return
    isLoading.value = true
    try {
      const res = await fetch('/api/providers')
      if (res.ok) {
        const data = await res.json()
        instances.value = data.instances || []
        activeProviderId.value = data.active_id || null
        saveToStorage()
      }
    } catch (e) {
      console.error('[Providers] Failed to load from backend:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function loadActive() {
    try {
      const res = await fetch('/api/providers/active')
      if (res.ok) {
        const data = await res.json()
        if (data.instance) {
          activeProviderId.value = data.instance.id
          // Update in list too
          const idx = instances.value.findIndex(i => i.id === data.instance.id)
          if (idx === -1) {
            instances.value.push(data.instance)
          }
          saveToStorage()
        }
      }
    } catch (e) {
      console.error('[Providers] Failed to load active:', e)
    }
  }

  async function setActive(id: string) {
    try {
      const res = await fetch('/api/providers/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: id }),
      })
      if (res.ok) {
        activeProviderId.value = id
        saveToStorage()
      }
    } catch (e) {
      console.error('[Providers] Failed to set active:', e)
    }
  }

  async function addInstance(inst: ProviderInstance) {
    try {
      const res = await fetch('/api/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(inst),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.instance) {
          instances.value.push(data.instance)
          saveToStorage()
        }
        return { success: true }
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        return { success: false, error: err.detail || 'Failed to add instance' }
      }
    } catch (e) {
      return { success: false, error: String(e) }
    }
  }

  async function updateInstance(id: string, inst: Partial<ProviderInstance>) {
    try {
      const body: Record<string, unknown> = { ...inst, id }
      const res = await fetch(`/api/providers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.instance) {
          const idx = instances.value.findIndex(i => i.id === id)
          if (idx !== -1) instances.value[idx] = data.instance
          saveToStorage()
        }
        return { success: true }
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        return { success: false, error: err.detail || 'Failed to update instance' }
      }
    } catch (e) {
      return { success: false, error: String(e) }
    }
  }

  async function removeInstance(id: string) {
    try {
      const res = await fetch(`/api/providers/${id}`, { method: 'DELETE' })
      if (res.ok) {
        instances.value = instances.value.filter(i => i.id !== id)
        // If removed was active, switch to first enabled
        if (activeProviderId.value === id) {
          const next = instances.value.find(i => i.enabled)
          activeProviderId.value = next?.id || null
        }
        saveToStorage()
        return { success: true }
      }
      return { success: false, error: 'Delete failed' }
    } catch (e) {
      return { success: false, error: String(e) }
    }
  }

  async function testInstance(id: string): Promise<{ ok: boolean; latency_ms?: number; error?: string }> {
    try {
      const res = await fetch(`/api/providers/${id}/test`, { method: 'POST' })
      return await res.json()
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  async function listInstanceModels(id: string, forceRefresh = false) {
    try {
      const res = await fetch(`/api/providers/${id}/models?force_refresh=${forceRefresh}`)
      if (res.ok) {
        const data = await res.json()
        return data.models || []
      }
      return []
    } catch (e) {
      console.error('[Providers] Failed to list models:', e)
      return []
    }
  }

  // ── Computed ───────────────────────────────────────────────────────────────

  const activeInstance = computed(() =>
    instances.value.find(i => i.id === activeProviderId.value) || null
  )

  // ── Init ────────────────────────────────────────────────────────────────────

  loadFromStorage()

  return {
    instances,
    activeProviderId,
    activeInstance,
    isLoading,
    isSyncing,
    loadFromBackend,
    loadActive,
    setActive,
    addInstance,
    updateInstance,
    removeInstance,
    testInstance,
    listInstanceModels,
  }
})
