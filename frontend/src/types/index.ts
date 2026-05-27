export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: Date
  updatedAt: Date
  userId?: string
  context?: Record<string, any>
}

export interface HardwareStatus {
  camera: boolean
  microphone: boolean
  screen: boolean
}

export interface SystemStatus {
  server: boolean
  ollama: boolean
}

export interface ChatRequest {
  message: string
  conversation_id?: string
  stream?: boolean
  model?: string
  force_refresh_models?: boolean
  messages?: Array<{ role: string; content: string }>
}

export interface ChatResponse {
  text: string
  response: string
  conversation_id?: string
}

export interface VoiceRequest {
  audioData?: string
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

export interface CameraFrameRequest {
  frameData: string
  prompt?: string
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