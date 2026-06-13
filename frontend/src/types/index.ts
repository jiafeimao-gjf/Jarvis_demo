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

export interface TTSResult {
  type: 'browser_tts' | 'qwen3_tts'
  text: string
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