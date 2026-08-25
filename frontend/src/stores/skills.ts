import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Skill, SkillConfig, SkillGroup, SkillTag } from '@/types'
import { useApi } from '@/composables/useApi'

const STORAGE_KEY = 'jarvis_skills'

interface PersistedState {
  skills: Skill[]
  config: SkillConfig
}

const DEFAULT_CONFIG: SkillConfig = {
  active_groups: ['default'],
  known_tags: [],
  known_groups: ['default'],
}

export const useSkillsStore = defineStore('skills', () => {
  const api = useApi()

  const skills = ref<Skill[]>([])
  const config = ref<SkillConfig>({ ...DEFAULT_CONFIG })
  const isLoading = ref(false)
  const isSyncing = ref(false)
  const errorMessage = ref<string | null>(null)

  // ── localStorage ──────────────────────────────────────────────────────────

  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        skills.value = parsed.skills || []
        config.value = parsed.config || DEFAULT_CONFIG
      }
    } catch (e) {
      console.error('[Skills] Failed to load from storage:', e)
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        skills: skills.value,
        config: config.value,
      } satisfies PersistedState))
    } catch (e) {
      console.error('[Skills] Failed to save to storage:', e)
    }
  }

  // ── Backend sync ──────────────────────────────────────────────────────────

  async function loadFromBackend() {
    if (isLoading.value) return
    isLoading.value = true
    errorMessage.value = null
    try {
      const [list, cfg] = await Promise.all([api.listSkills(true), api.getSkillConfig()])
      skills.value = list
      config.value = cfg
      saveToStorage()
    } catch (e) {
      errorMessage.value = String(e)
      console.error('[Skills] Failed to load from backend:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function refreshFromDisk() {
    isSyncing.value = true
    errorMessage.value = null
    try {
      await api.refreshSkillsFromDisk()
      await loadFromBackend()
    } catch (e) {
      errorMessage.value = String(e)
    } finally {
      isSyncing.value = false
    }
  }

  async function addSkill(input: Partial<Skill>): Promise<{ success: boolean; error?: string }> {
    errorMessage.value = null
    try {
      const created = await api.createSkill(input)
      skills.value.push(created)
      saveToStorage()
      return { success: true }
    } catch (e) {
      const msg = String(e)
      errorMessage.value = msg
      return { success: false, error: msg }
    }
  }

  async function updateSkill(id: string, partial: Partial<Skill>): Promise<{ success: boolean; error?: string }> {
    errorMessage.value = null
    try {
      const updated = await api.updateSkill(id, partial)
      const idx = skills.value.findIndex(s => s.id === id)
      if (idx !== -1) skills.value[idx] = updated
      saveToStorage()
      return { success: true }
    } catch (e) {
      const msg = String(e)
      errorMessage.value = msg
      return { success: false, error: msg }
    }
  }

  async function removeSkill(id: string): Promise<{ success: boolean; error?: string }> {
    errorMessage.value = null
    try {
      await api.deleteSkill(id)
      skills.value = skills.value.filter(s => s.id !== id)
      saveToStorage()
      return { success: true }
    } catch (e) {
      const msg = String(e)
      errorMessage.value = msg
      return { success: false, error: msg }
    }
  }

  async function toggleSkill(id: string) {
    try {
      const updated = await api.toggleSkill(id)
      if (updated) {
        const idx = skills.value.findIndex(s => s.id === id)
        if (idx !== -1) skills.value[idx] = updated
        saveToStorage()
      }
    } catch (e) {
      errorMessage.value = String(e)
    }
  }

  async function setActiveGroups(groups: string[]) {
    try {
      const updated = await api.setActiveGroups(groups)
      config.value.active_groups = updated
      saveToStorage()
    } catch (e) {
      errorMessage.value = String(e)
    }
  }

  async function renameTag(oldName: string, newName: string): Promise<boolean> {
    try {
      await api.renameSkillTag(oldName, newName)
      await loadFromBackend()
      return true
    } catch (e) {
      errorMessage.value = String(e)
      return false
    }
  }

  async function renameGroup(oldName: string, newName: string): Promise<boolean> {
    try {
      await api.renameSkillGroup(oldName, newName)
      await loadFromBackend()
      return true
    } catch (e) {
      errorMessage.value = String(e)
      return false
    }
  }

  async function deleteTag(name: string): Promise<boolean> {
    try {
      await api.deleteSkillTag(name)
      await loadFromBackend()
      return true
    } catch (e) {
      errorMessage.value = String(e)
      return false
    }
  }

  async function deleteGroup(name: string): Promise<boolean> {
    try {
      await api.deleteSkillGroup(name)
      await loadFromBackend()
      return true
    } catch (e) {
      errorMessage.value = String(e)
      return false
    }
  }

  // ── Computed ──────────────────────────────────────────────────────────────

  const enabledSkills = computed(() =>
    skills.value.filter(s => s.enabled && !s.missing)
  )

  const tags = computed<SkillTag[]>(() => {
    const counts = new Map<string, number>()
    for (const s of skills.value) {
      for (const t of s.tags) counts.set(t, (counts.get(t) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([name, skill_count]) => ({ name, skill_count }))
      .sort((a, b) => b.skill_count - a.skill_count)
  })

  const groups = computed<SkillGroup[]>(() => {
    const active = new Set(config.value.active_groups)
    const counts = new Map<string, number>()
    for (const s of skills.value) {
      for (const g of s.groups) counts.set(g, (counts.get(g) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([name, skill_count]) => ({ name, skill_count, is_active: active.has(name) }))
      .sort((a, b) => b.skill_count - a.skill_count)
  })

  // ── Init ──────────────────────────────────────────────────────────────────

  loadFromStorage()

  return {
    skills,
    config,
    isLoading,
    isSyncing,
    errorMessage,
    enabledSkills,
    tags,
    groups,
    loadFromBackend,
    refreshFromDisk,
    addSkill,
    updateSkill,
    removeSkill,
    toggleSkill,
    setActiveGroups,
    renameTag,
    renameGroup,
    deleteTag,
    deleteGroup,
  }
})
