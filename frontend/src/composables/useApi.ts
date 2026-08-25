import { ref } from 'vue'
import type {
  ChatRequest,
  ChatResponse,
  VoiceResponse,
  CameraResponse,
  TaskResult,
  MemoryResponse,
  MemoryQueryResponse,
  AudioChunkEvent,
  AudioDoneEvent,
  TTSFallbackEvent,
  TTSResult,
  VoiceRefInfo,
  TTSStatus,
  Skill,
  SkillConfig,
  SkillGroup,
  SkillTag,
} from '@/types'

const API_BASE = '/api'

export function useApi() {
  const error = ref<string | null>(null)

  async function chat(request: ChatRequest): Promise<ChatResponse> {
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
        conversation_id: data.conversation_id,
        topic: data.topic,
      }
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function updateConversationTopic(conversationId: string, topic: string): Promise<{ success: boolean; topic: string }> {
    const res = await fetch(`${API_BASE}/memory/conversation/${conversationId}/topic`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic })
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function chatStream(
    request: ChatRequest,
    onToken: (token: string) => void,
    onDone?: () => void,
    onStatus?: (status: string | Record<string, unknown>) => void,
    onThinking?: (chunk: string) => void,
    signal?: AbortSignal,
    onTopicUpdate?: (topic: string) => void,
    // TTS 回调 (后端流式推 audio chunks)
    onAudio?: (chunk: AudioChunkEvent) => void,
    onAudioDone?: (evt: AudioDoneEvent) => void,
    onTTSFallback?: (evt: TTSFallbackEvent) => void,
  ): Promise<void> {
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No reader')

      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = 'message'  // SSE event: 行 (默认 message)

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 逐行解析 SSE 协议: event: <name>\ndata: <data>\n\n
        while (buffer.includes('\n')) {
          const newlineIndex = buffer.indexOf('\n')
          const line = buffer.slice(0, newlineIndex)
          buffer = buffer.slice(newlineIndex + 1)

          if (line === '') {
            // 空行 — 一个 event block 结束, 重置 event 名
            currentEvent = 'message'
          } else if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const dataStr = line.slice(5).trim()
            if (!dataStr) continue
            let data: any
            try {
              data = JSON.parse(dataStr)
            } catch {
              continue
            }
            // 按 SSE event 名分发
            if (currentEvent === 'audio') {
              onAudio?.(data as AudioChunkEvent)
            } else if (currentEvent === 'audio_done') {
              onAudioDone?.(data as AudioDoneEvent)
            } else if (currentEvent === 'tts_fallback') {
              onTTSFallback?.(data as TTSFallbackEvent)
            } else if (currentEvent === 'token' || currentEvent === 'message') {
              // 默认 message + token: 走原 data.type 分类
              if (data.type === 'token' && data.content) {
                onToken(data.content)
              } else if (data.type === 'done') {
                onDone?.()
              } else if (data.type === 'status' && data.content) {
                onStatus?.(data.content)
              } else if (data.type === 'tool_call') {
                onStatus?.({
                  type: 'tool_call',
                  tool: data.tool,
                  action: data.action,
                  params: data.params || {},
                })
              } else if (data.type === 'tool_result') {
                onStatus?.({
                  type: 'tool_result',
                  tool: data.tool,
                  action: data.action,
                  status: data.status,
                  result: data.result,
                })
              } else if (data.type === 'thinking') {
                onThinking?.(data.content)
              } else if (data.type === 'thinking_start') {
                onThinking?.('')
              } else if (data.type === 'topic_update' && data.topic) {
                onTopicUpdate?.(data.topic)
              }
            } else if (currentEvent === 'tool') {
              // tool 事件: data 已经是 JSON object, 直接传给 onStatus
              onStatus?.(data)
            }
          }
        }
      }
      // Stream ended normally — ensure onDone is called even if server didn't send done event
      onDone?.()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function voice(audioBase64: string, conversationId?: string): Promise<VoiceResponse> {
    error.value = null
    try {
      const res = await fetch(`${API_BASE}/voice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audioData: audioBase64, conversationId })
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  // ============ 声音克隆 API ============

  async function voiceRefInfo(): Promise<VoiceRefInfo> {
    const res = await fetch(`${API_BASE}/voice/ref/info`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function uploadVoiceRef(file: File): Promise<{ ok: boolean; filename: string; size_bytes: number; duration_sec?: number; sample_rate?: number; channels?: number }> {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${API_BASE}/voice/ref/upload`, {
      method: 'POST',
      body: fd,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  }

  async function setRefText(text: string): Promise<{ ok: boolean; text: string }> {
    const res = await fetch(`${API_BASE}/voice/ref/text`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  }

  async function deleteVoiceRef(): Promise<{ ok: boolean }> {
    const res = await fetch(`${API_BASE}/voice/ref`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function listVoiceHistory(): Promise<{ items: Array<{ filename: string; size_bytes: number; mtime: number; has_text: boolean }> }> {
    const res = await fetch(`${API_BASE}/voice/ref/history`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function synthesize(text: string, speed?: number): Promise<TTSResult> {
    const res = await fetch(`${API_BASE}/voice/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, speed }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  async function ttsStatus(): Promise<TTSStatus> {
    const res = await fetch(`${API_BASE}/voice/status`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  function refAudioUrl(): string {
    return `${API_BASE}/voice/ref/audio?t=${Date.now()}`
  }

  function cloneAudioUrl(audioPath: string): string {
    // audioPath 形如 "/api/voice/audio/xxx.wav"
    if (audioPath.startsWith('http')) return audioPath
    if (audioPath.startsWith(API_BASE)) return audioPath
    return `${API_BASE}${audioPath.replace(/^\/?api/, '')}`
  }

  async function analyzeCameraFrame(
    frameBase64: string,
    prompt = '描述这张图片'
  ): Promise<CameraResponse> {
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

  // ============ 技能管理 API ============

  async function listSkills(includeMissing = false): Promise<Skill[]> {
    const res = await fetch(`${API_BASE}/skills?include_missing=${includeMissing}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.skills || []
  }

  async function getSkill(id: string): Promise<Skill> {
    const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(id)}`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    return data.skill
  }

  async function createSkill(skill: Partial<Skill>): Promise<Skill> {
    const res = await fetch(`${API_BASE}/skills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(skill),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    return data.skill
  }

  async function updateSkill(id: string, partial: Partial<Skill>): Promise<Skill> {
    const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    return data.skill
  }

  async function deleteSkill(id: string): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return true
  }

  async function toggleSkill(id: string): Promise<Skill | null> {
    const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(id)}/toggle`, {
      method: 'PATCH',
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.skill || null
  }

  async function reorderSkills(orderedIds: string[]): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/reorder`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ordered_ids: orderedIds }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return true
  }

  async function refreshSkillsFromDisk(): Promise<{ count: number }> {
    const res = await fetch(`${API_BASE}/skills/refresh`, { method: 'POST' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return { count: data.count || 0 }
  }

  async function getSkillConfig(): Promise<SkillConfig> {
    const res = await fetch(`${API_BASE}/skills/config`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.config
  }

  async function setActiveGroups(groups: string[]): Promise<string[]> {
    const res = await fetch(`${API_BASE}/skills/config/active_groups`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groups }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.active_groups || []
  }

  async function getSkillGroups(): Promise<SkillGroup[]> {
    const res = await fetch(`${API_BASE}/skills/groups`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.groups || []
  }

  async function getSkillTags(): Promise<SkillTag[]> {
    const res = await fetch(`${API_BASE}/skills/tags`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.tags || []
  }

  async function renameSkillTag(oldName: string, newName: string): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/tags/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old: oldName, new: newName }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return true
  }

  async function renameSkillGroup(oldName: string, newName: string): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/groups/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old: oldName, new: newName }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return true
  }

  async function deleteSkillTag(name: string): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/tags/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return true
  }

  async function deleteSkillGroup(name: string): Promise<boolean> {
    const res = await fetch(`${API_BASE}/skills/groups/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return true
  }

  return {
    error,
    chat,
    chatStream,
    voice,
    analyzeCameraFrame,
    retrieveMemories,
    saveMemory,
    executeTask,
    getStatus,
    updateConversationTopic,
    // 声音克隆
    voiceRefInfo,
    uploadVoiceRef,
    setRefText,
    deleteVoiceRef,
    listVoiceHistory,
    synthesize,
    ttsStatus,
    refAudioUrl,
    cloneAudioUrl,
    // 技能管理
    listSkills,
    getSkill,
    createSkill,
    updateSkill,
    deleteSkill,
    toggleSkill,
    reorderSkills,
    refreshSkillsFromDisk,
    getSkillConfig,
    setActiveGroups,
    getSkillGroups,
    getSkillTags,
    renameSkillTag,
    renameSkillGroup,
    deleteSkillTag,
    deleteSkillGroup,
  }
}