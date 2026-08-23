export type ProviderType = 'ollama' | 'openai' | 'anthropic' | 'minimax'

export interface ProviderInstance {
  id: string
  type: ProviderType
  display_name: string
  base_url?: string
  api_key?: string
  default_model: string
  enabled: boolean
  timeout?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool' | 'tool_result'
  content: string
  timestamp: Date
  image?: string
  thinking?: string  // Model reasoning/thinking content
}

export interface Conversation {
  id: string
  title: string
  topic?: string  // 对话主题 (auto-generated or user-edited)
  messages: Message[]
  createdAt: Date
  updatedAt: Date
  userId: string
  context?: Record<string, any>
}

export interface HardwareStatus {
  camera: boolean
  microphone: boolean
}

export interface SystemStatus {
  server: boolean
  ollama: boolean
}

export interface ChatRequest {
  message: string
  conversation_id?: string
  user_id?: string
  stream?: boolean
  model?: string
  force_refresh_models?: boolean
  messages?: Array<{ role: string; content: string }>
  provider_id?: string
  enable_tts?: boolean  // 是否启用 TTS（声音克隆 / 浏览器降级）。默认 true
}

export interface ChatResponse {
  text: string
  response: string
  conversation_id?: string
  topic?: string
}

export interface VoiceResponse {
  text: string
  response: string
  tts: TTSResult
}

/**
 * TTS 返回结果。前端按 `type` 路由:
 *  - voice_clone: <audio :src=audio_url> 播放
 *  - browser_tts: window.speechSynthesis.speak(text)
 */
export type TTSResult =
  | { type: 'voice_clone'; audio_url: string; duration: number; text: string; mime: string }
  | { type: 'browser_tts'; text: string }

/** SSE 流式音频 chunk (来自 /api/chat/stream event: audio) */
export interface AudioChunkEvent {
  type: 'audio_chunk'
  index: number
  sample_rate: number
  channels: number
  sample_width: number
  duration_ms: number
  pcm_b64: string
}

/** SSE 流式音频结束 (来自 /api/chat/stream event: audio_done) */
export interface AudioDoneEvent {
  type: 'audio_done'
  sentences: number
  sample_rate: number
  sample_width: number
  channels: number
}

/** SSE 降级事件 — 后端 TTS 不可用, 前端用浏览器 SpeechSynthesis 兜底 */
export interface TTSFallbackEvent {
  type: 'tts_fallback'
  text: string
}

/** 参考音频信息 (来自 /api/voice/ref/info) */
export interface VoiceRefInfo {
  exists: boolean
  filename?: string
  text?: string
  size_bytes?: number
  mtime?: number
  tts_available?: boolean
  duration_sec?: number
  sample_rate?: number
  channels?: number
}

/** TTS 子系统状态 (来自 /api/voice/status) */
export interface TTSStatus {
  enabled: boolean
  ref_exists: boolean
  ref_info: VoiceRefInfo
  device: string
  available: boolean
  model_name: string
  last_error: string | null
}

export interface CameraResponse {
  success: boolean
  analysis?: string
  error?: string
}

export interface MemoryItem {
  key: string
  content: string
  score?: number
  metadata?: Record<string, unknown>
}

export interface TaskResult {
  taskId: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: string
}

export interface MemoryResponse {
  success: boolean
  memory_id?: string
}

export interface MemoryQueryResponse {
  results: MemoryItem[]
  count: number
}