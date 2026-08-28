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

// ── Skills ──────────────────────────────────────────────────────────────────

export interface Skill {
  id: string
  name: string
  description: string
  content: string
  tags: string[]
  groups: string[]
  enabled: boolean
  order: number
  file_path: string
  created_at?: string
  updated_at?: string
  missing?: boolean  // DB row exists but file deleted externally
}

export interface SkillConfig {
  active_groups: string[]
  known_tags: string[]
  known_groups: string[]
}

export interface SkillGroup {
  name: string
  skill_count: number
  is_active: boolean
}

export interface SkillTag {
  name: string
  skill_count: number
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

// ── LLM 调用日志 ────────────────────────────────────────────────────────

/** 单条调用的摘要 (列表用, 不含完整 body) */
export interface LLMCallLogSummary {
  call_id: string
  timestamp: string
  timestamp_ms: number
  model: string
  provider: string
  provider_protocol: string | null
  conversation_id: string | null
  source: string
  latency_ms: number
  status: 'success' | 'error' | 'stream_interrupted' | string
  messages_count: number
  has_tool_use: boolean
  thinking_chars: number
  response_chars: number
  error: string | null
}

/** 单条调用的完整详情 */
export interface LLMCallLogDetail {
  call_id: string
  timestamp: string
  timestamp_ms: number
  model: string
  provider: string
  provider_protocol: string | null
  conversation_id: string | null
  source: string
  latency_ms: number
  status: string
  error: string | null
  request: {
    messages?: any[]
    tools?: any[]
    stream?: boolean
    max_tokens?: number
    temperature?: number
    raw_http_body?: any  // 原始 HTTP request payload (model + max_tokens + tools 摘要)
    [key: string]: any
  }
  response: {
    content?: string
    thinking?: string
    content_blocks?: any[]
    usage?: any
    raw?: any
    raw_http_body?: any  // 原始 HTTP response (非流场景)
    raw_stream_events?: any[]  // 原始 SSE chunks (流场景)
    stop_reason?: string
    [key: string]: any
  }
  metadata: Record<string, any>
}

/** 列表 API 响应 */
export interface LLMCallLogListResponse {
  date: string
  total: number
  offset: number
  limit: number
  items: LLMCallLogSummary[]
}

/** 统计摘要响应 */
export interface LLMCallLogStats {
  date: string
  total: number
  by_status: Record<string, number>
  by_provider: Record<string, number>
  by_model: Record<string, number>
  latency_ms: {
    avg: number
    p50: number
    p95: number
    count: number
  }
  error_rate: number
}