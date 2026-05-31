import { ref, onUnmounted, computed } from 'vue'
import { useApi } from './useApi'

export function useSpeechRecognition() {
  const api = useApi()
  const isRecording = ref(false)
  const transcript = ref('')
  const interimTranscript = ref('')
  const isProcessing = ref(false)
  const error = ref<string | null>(null)

  let recognition: any = null
  let mediaRecorder: MediaRecorder | null = null
  let audioChunks: Blob[] = []

  const hasTranscript = computed(() => transcript.value.trim().length > 0)

  function initRecognition(): boolean {
    const SpeechRecognition: any =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) {
      error.value = '浏览器不支持语音识别'
      return false
    }

    recognition = new SpeechRecognition()
    recognition.lang = 'zh-CN'
    recognition.continuous = true
    recognition.interimResults = true

    recognition.onresult = (event: any) => {
      let final = ''
      let interim = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          final += result[0].transcript
        } else {
          interim += result[0].transcript
        }
      }

      if (final) {
        transcript.value += final
      }
      interimTranscript.value = interim
    }

    recognition.onerror = (event: any) => {
      error.value = event.error
      isRecording.value = false
      if (event.error !== 'no-speech') {
        console.error('Speech recognition error:', event.error)
      }
    }

    recognition.onend = () => {
      isRecording.value = false
    }

    return true
  }

  function startRecording() {
    if (isRecording.value) return

    error.value = null
    transcript.value = ''
    interimTranscript.value = ''

    if (!recognition) {
      if (!initRecognition()) return
    }

    try {
      recognition.start()
      isRecording.value = true
    } catch (e) {
      error.value = (e as Error).message
      console.error('Failed to start recognition:', e)
    }
  }

  function stopRecording(): string {
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        // Ignore if already stopped
      }
    }
    isRecording.value = false
    return transcript.value
  }

  let _audioStream: MediaStream | null = null
  let _resolveCapture: ((v: string | null) => void) | null = null

  async function startCapture(): Promise<boolean> {
    audioChunks = []
    try {
      _audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaRecorder = new MediaRecorder(_audioStream)
      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) audioChunks.push(event.data)
      }
      mediaRecorder.start()
      isRecording.value = true
      return true
    } catch (e) {
      error.value = (e as Error).message
      return false
    }
  }

  function stopCapture(): Promise<string | null> {
    return new Promise((resolve) => {
      _resolveCapture = resolve
      if (mediaRecorder?.state === 'recording') {
        mediaRecorder.onstop = async () => {
          const blob = new Blob(audioChunks, { type: 'audio/webm' })
          const reader = new FileReader()
          reader.onloadend = () => {
            const base64 = (reader.result as string).split(',')[1] || null
            _audioStream?.getTracks().forEach(t => t.stop())
            _audioStream = null
            isRecording.value = false
            resolve(base64)
          }
          reader.readAsDataURL(blob)
        }
        mediaRecorder.stop()
      } else {
        isRecording.value = false
        resolve(null)
      }
    })
  }

  async function captureAudio(): Promise<string | null> {
    // Legacy: auto-stop after 5s (kept for backward compat)
    audioChunks = []
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaRecorder = new MediaRecorder(stream)
      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) audioChunks.push(event.data)
      }
      mediaRecorder.start()
      return new Promise((resolve) => {
        mediaRecorder!.onstop = async () => {
          const blob = new Blob(audioChunks, { type: 'audio/webm' })
          const reader = new FileReader()
          reader.onloadend = () => {
            const base64 = (reader.result as string).split(',')[1]
            stream.getTracks().forEach((track) => track.stop())
            resolve(base64)
          }
          reader.readAsDataURL(blob)
        }
        setTimeout(() => {
          if (mediaRecorder?.state === 'recording') mediaRecorder.stop()
        }, 5000)
      })
    } catch (e) {
      error.value = (e as Error).message
      return null
    }
  }

  async function processVoiceInput(): Promise<string | null> {
    isProcessing.value = true
    error.value = null

    try {
      const audioBase64 = await captureAudio()
      if (!audioBase64) {
        isProcessing.value = false
        return null
      }

      const response = await api.voice(audioBase64)
      transcript.value = response.text
      return response.response
    } catch (e) {
      error.value = (e as Error).message
      return null
    } finally {
      isProcessing.value = false
    }
  }

  function speak(text: string) {
    if (!('speechSynthesis' in window)) {
      console.warn('Browser does not support speech synthesis')
      return
    }

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-CN'
    utterance.rate = 1.0
    utterance.pitch = 1.0
    speechSynthesis.speak(utterance)
  }

  function stopSpeaking() {
    speechSynthesis.cancel()
  }

  onUnmounted(() => {
    if (recognition) {
      try {
        recognition.abort()
      } catch {
        // Ignore
      }
    }
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop()
    }
    stopSpeaking()
  })

  return {
    isRecording,
    transcript,
    interimTranscript,
    isProcessing,
    hasTranscript,
    error,
    startRecording,
    stopRecording,
    captureAudio,
    startCapture,
    stopCapture,
    processVoiceInput,
    speak,
    stopSpeaking
  }
}