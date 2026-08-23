/**
 * Web Audio API PCM int16 播放器
 *
 * 用法:
 *   const pcmPlayer = usePCMPlayer()
 *   pcmPlayer.pushChunk(pcmB64, { sample_rate: 24000 })
 *   ...
 *   pcmPlayer.stop()    // 中断播放
 *
 * 设计要点:
 *  - 内部维护 AudioContext + 缓冲队列
 *  - 按时间戳 nextStartTime 排程, 不会卡顿也不会乱序
 *  - 不依赖 chunk.index, 容忍丢包 / 重排
 *  - stop() 时彻底释放 AudioContext
 */
import { ref } from 'vue'

export interface PCMChunkMeta {
  sample_rate: number
  channels?: number
  sample_width?: number
}

interface QueuedChunk {
  samples: Float32Array
  sampleRate: number
}

export function usePCMPlayer() {
  const isPlaying = ref(false)
  const lastError = ref<string | null>(null)

  let ctx: AudioContext | null = null
  let nextStartTime = 0
  const queue: QueuedChunk[] = []
  let scheduled = false

  function ensureCtx(sampleRate: number): AudioContext {
    if (ctx && ctx.sampleRate !== sampleRate) {
      // sample rate 变了, 重建 ctx
      ctx.close().catch(() => {})
      ctx = null
    }
    if (!ctx) {
      // @ts-ignore - AudioContext 在 Safari 上是 webkitAudioContext
      ctx = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate,
      })
      nextStartTime = ctx.currentTime + 0.05
    }
    return ctx
  }

  function schedule(): void {
    if (!ctx || scheduled) return
    scheduled = true
    isPlaying.value = true

    const drain = () => {
      if (!ctx) return
      while (queue.length > 0) {
        const { samples, sampleRate } = queue.shift()!
        const buf = ctx.createBuffer(1, samples.length, sampleRate)
        buf.copyToChannel(samples, 0)
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        const startAt = Math.max(nextStartTime, ctx.currentTime)
        src.start(startAt)
        nextStartTime = startAt + buf.duration
      }
      scheduled = false
    }

    // 排程到下一个 idle frame, 让多个 pushChunk 攒一批再 schedule
    requestAnimationFrame(drain)
  }

  function pushChunk(pcmB64: string, meta: PCMChunkMeta): void {
    try {
      // base64 → bytes
      const raw = atob(pcmB64)
      const view = new DataView(new ArrayBuffer(raw.length))
      for (let i = 0; i < raw.length; i++) {
        view.setUint8(i, raw.charCodeAt(i))
      }
      const sampleCount = raw.length / 2  // int16 = 2 bytes
      const samples = new Float32Array(sampleCount)
      for (let i = 0; i < sampleCount; i++) {
        samples[i] = view.getInt16(i * 2, true) / 32768
      }

      const sr = meta.sample_rate || 24000
      const audioCtx = ensureCtx(sr)
      queue.push({ samples, sampleRate: audioCtx.sampleRate })
      schedule()
    } catch (e) {
      lastError.value = (e as Error).message
    }
  }

  function stop(): void {
    if (ctx) {
      ctx.close().catch(() => { /* ignore */ })
      ctx = null
    }
    queue.length = 0
    nextStartTime = 0
    scheduled = false
    isPlaying.value = false
  }

  /**
   * 在用户手势内调用 (例如 click handler), 创建并 resume AudioContext,
   * 之后即使经历任意 await, 该 ctx 仍可被 resume/play — 用来绕开浏览器
   * autoplay 策略 (HTMLAudioElement.play() 跨 await 会被拒)。
   */
  function ensureResumed(): void {
    const sr = 24000
    const audioCtx = ensureCtx(sr)
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => { /* ignore */ })
    }
  }

  /**
   * 通过 Web Audio API 播放任意可解码的音频 URL (wav/mp3/ogg...)。
   * 适用于后端返回 audio_url 但 synthesize 跨 await 完成后
   * HTMLAudioElement.play() 被浏览器拒绝的场景。
   *
   * 流程: fetch → arrayBuffer → decodeAudioData → BufferSource.start
   * 必须先调 ensureResumed() (在用户 click 内) 才能跨 await 仍可播。
   */
  async function playUrl(url: string): Promise<void> {
    const sr = 24000
    const audioCtx = ensureCtx(sr)
    if (audioCtx.state === 'suspended') {
      await audioCtx.resume()
    }
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`fetch audio failed: ${resp.status}`)
    const ab = await resp.arrayBuffer()
    const buf = await audioCtx.decodeAudioData(ab)
    const src = audioCtx.createBufferSource()
    src.buffer = buf
    src.connect(audioCtx.destination)
    isPlaying.value = true
    src.onended = () => { isPlaying.value = false }
    src.start(0)
  }

  return {
    isPlaying,
    lastError,
    pushChunk,
    stop,
    ensureResumed,
    playUrl,
  }
}