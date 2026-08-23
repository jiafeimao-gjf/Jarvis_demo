/**
 * 声音克隆 Pinia store — 缓存 ref 状态 + TTS 子系统状态。
 *
 * 用法:
 *   const store = useVoiceCloneStore()
 *   await store.refresh()      // 进入 Settings 时调一次
 *   await store.uploadFile(f)  // 上传参考音频
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'
import type { VoiceRefInfo, TTSStatus } from '@/types'

export const useVoiceCloneStore = defineStore('voice_clone', () => {
  const api = useApi()

  const refInfo = ref<VoiceRefInfo | null>(null)
  const status = ref<TTSStatus | null>(null)
  const isLoading = ref(false)
  const lastError = ref<string | null>(null)

  async function refresh() {
    isLoading.value = true
    lastError.value = null
    try {
      const [info, st] = await Promise.all([
        api.voiceRefInfo(),
        api.ttsStatus(),
      ])
      refInfo.value = info
      status.value = st
    } catch (e) {
      lastError.value = (e as Error).message
    } finally {
      isLoading.value = false
    }
  }

  async function uploadFile(file: File) {
    isLoading.value = true
    lastError.value = null
    try {
      await api.uploadVoiceRef(file)
      await refresh()
    } catch (e) {
      lastError.value = (e as Error).message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function setRefText(text: string) {
    await api.setRefText(text)
    await refresh()
  }

  async function remove() {
    await api.deleteVoiceRef()
    await refresh()
  }

  return {
    refInfo,
    status,
    isLoading,
    lastError,
    refresh,
    uploadFile,
    setRefText,
    remove,
  }
})