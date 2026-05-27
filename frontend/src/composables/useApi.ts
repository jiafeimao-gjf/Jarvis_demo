import { ref } from 'vue'
import type {
  ChatRequest,
  ChatResponse,
  VoiceResponse,
  CameraResponse,
  MemoryItem,
  TaskResult,
  MemoryResponse,
  MemoryQueryResponse
} from '@/types'

const API_BASE = '/api'

export function useApi() {
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function chat(request: ChatRequest): Promise<ChatResponse> {
    isLoading.value = true
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      return {
        text: data.text,
        response: data.response,
        conversation_id: data.conversation_id
      }
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function chatStream(
    request: ChatRequest,
    onToken: (token: string) => void,
    onDone?: () => void
  ): Promise<void> {
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No reader')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete events (lines starting with 'data: ')
        while (buffer.includes('\n')) {
          const newlineIndex = buffer.indexOf('\n')
          const line = buffer.slice(0, newlineIndex)
          buffer = buffer.slice(newlineIndex + 1)

          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim()
            if (dataStr) {
              try {
                const data = JSON.parse(dataStr)
                if (data.type === 'token' && data.content) {
                  onToken(data.content)
                } else if (data.type === 'done') {
                  onDone?.()
                }
              } catch {
                // Incomplete JSON, will be completed in next chunk
              }
            }
          }
        }
      }
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function voice(audioBase64: string): Promise<VoiceResponse> {
    isLoading.value = true
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/voice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audioData: audioBase64 })
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function analyzeCameraFrame(
    frameBase64: string,
    prompt = '描述这张图片'
  ): Promise<CameraResponse> {
    isLoading.value = true
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/camera/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frame_data: frameBase64, prompt })
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function retrieveMemories(
    query: string,
    topK = 5
  ): Promise<MemoryQueryResponse> {
    const res = await fetch(
      `${API_BASE}/memory?query=${encodeURIComponent(query)}&top_k=${topK}`
    )
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function saveMemory(
    key: string,
    content: string
  ): Promise<MemoryResponse> {
    const res = await fetch(`${API_BASE}/memory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, content })
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function executeTask(task: string): Promise<TaskResult> {
    isLoading.value = true
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task })
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function getStatus(): Promise<{
    status: string
    version: string
    systems: Record<string, unknown>
  } | null> {
    try {
      const res = await fetch(`${API_BASE}/status`)
      if (res.ok) {
        return res.json()
      }
    } catch {
      // Ignore network errors
    }
    return null
  }

  return {
    isLoading,
    error,
    chat,
    chatStream,
    voice,
    analyzeCameraFrame,
    retrieveMemories,
    saveMemory,
    executeTask,
    getStatus
  }
}