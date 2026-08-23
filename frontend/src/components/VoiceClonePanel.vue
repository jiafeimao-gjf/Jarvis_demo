<script setup lang="ts">
/**
 * 声音克隆设置面板
 * - 上传/录制参考音频
 * - 设置参考文本 (ref_text, F5-TTS 必填)
 * - 试听 / 试合成 / 删除
 */
import { ref, onMounted, computed } from 'vue'
import { useVoiceCloneStore } from '@/stores/voice_clone'
import { useApi } from '@/composables/useApi'

const store = useVoiceCloneStore()
const api = useApi()

const fileInput = ref<HTMLInputElement | null>(null)
const refTextInput = ref('')
const isUploading = ref(false)
const isRecording = ref(false)
const isSynthesizing = ref(false)
const testText = ref('你好，这是克隆声音测试。')
const testAudioUrl = ref<string | null>(null)
const uploadError = ref<string | null>(null)
const mediaRecorder = ref<MediaRecorder | null>(null)
const audioChunks = ref<Blob[]>([])

// 录音时提示用户念出的固定文本（与后端默认 ref_text 一致）
const RECORDING_PROMPT = '我是顾家飞，请克隆我的声音，我是要成为海贼王的男人。'

const status = computed(() => store.status)
const refInfo = computed(() => store.refInfo)
const isAvailable = computed(() => status.value?.available ?? false)
const deviceLabel = computed(() => {
  const d = status.value?.device
  if (!d) return ''
  return d === 'mps' ? 'Apple Silicon (MPS)' : d === 'cuda' ? 'CUDA' : d === 'cpu' ? 'CPU' : d
})

onMounted(() => {
  store.refresh()
  if (refInfo.value?.text) {
    refTextInput.value = refInfo.value.text
  }
})

function pickFile() {
  fileInput.value?.click()
}

async function onFileSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  await uploadRef(file)
  target.value = ''
}

async function uploadRef(file: Blob) {
  isUploading.value = true
  uploadError.value = null
  try {
    await store.uploadFile(file as File)
  } catch (e) {
    uploadError.value = (e as Error).message
  } finally {
    isUploading.value = false
  }
}

async function saveRefText() {
  const text = refTextInput.value.trim()
  if (!text) {
    uploadError.value = '参考文本不能为空'
    return
  }
  try {
    await store.setRefText(text)
    uploadError.value = null
  } catch (e) {
    uploadError.value = (e as Error).message
  }
}

async function deleteRef() {
  if (!confirm('确定删除当前参考音频？克隆将自动降级到浏览器 TTS。')) return
  await store.remove()
  refTextInput.value = ''
}

// ============ 录音 (MediaRecorder) ============

async function toggleRecording() {
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    audioChunks.value = []
    mediaRecorder.value = new MediaRecorder(stream)
    mediaRecorder.value.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.value.push(e.data)
    }
    mediaRecorder.value.onstop = async () => {
      stream.getTracks().forEach(t => t.stop())
      const blob = new Blob(audioChunks.value, { type: 'audio/webm' })
      const file = new File([blob], 'recorded.webm', { type: 'audio/webm' })
      await uploadRef(file)
    }
    mediaRecorder.value.start()
    isRecording.value = true
  } catch (e) {
    uploadError.value = `无法访问麦克风：${(e as Error).message}`
  }
}

function stopRecording() {
  if (mediaRecorder.value && mediaRecorder.value.state === 'recording') {
    mediaRecorder.value.stop()
  }
  isRecording.value = false
}

// ============ 试合成 ============

async function testSynthesize() {
  if (!testText.value.trim()) return
  isSynthesizing.value = true
  testAudioUrl.value = null
  try {
    const result = await api.synthesize(testText.value)
    if (result.type === 'voice_clone') {
      testAudioUrl.value = api.cloneAudioUrl(result.audio_url)
    } else {
      uploadError.value = '当前未启用声音克隆（后端降级到了浏览器 TTS）'
    }
  } catch (e) {
    uploadError.value = (e as Error).message
  } finally {
    isSynthesizing.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatDuration(sec: number | undefined): string {
  if (!sec) return ''
  return `${sec.toFixed(1)} 秒`
}
</script>

<template>
  <div class="space-y-3">
    <!-- 状态卡片 -->
    <div class="flex items-center justify-between p-3 rounded-lg bg-background/50 border border-border">
      <div class="flex-1">
        <div class="text-sm font-medium">
          <span v-if="isAvailable" class="text-green-500">✓ 已就绪 — {{ deviceLabel }}</span>
          <span v-else-if="status?.enabled && !status.ref_exists" class="text-yellow-500">⚠ 未上传参考音频</span>
          <span v-else-if="!status?.enabled" class="text-muted-foreground">○ 后端未启用 (VOICE_CLONE__ENABLED=false)</span>
          <span v-else class="text-destructive">✗ F5-TTS 不可用 — {{ status?.last_error || '检查 pip install f5-tts' }}</span>
        </div>
        <div v-if="refInfo?.exists" class="text-xs text-muted-foreground mt-1">
          {{ refInfo.filename }} · {{ formatSize(refInfo.size_bytes || 0)
          }}<span v-if="refInfo.duration_sec"> · {{ formatDuration(refInfo.duration_sec)
          }} · {{ refInfo.sample_rate }}Hz</span>
        </div>
      </div>
      <button
        class="text-xs text-muted-foreground hover:text-foreground px-2 py-1"
        @click="store.refresh()"
        :disabled="store.isLoading"
      >
        刷新
      </button>
    </div>

    <!-- 上传区 -->
    <div class="flex items-center gap-2">
      <button
        class="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 text-sm"
        @click="pickFile"
        :disabled="isUploading || isRecording"
      >
        {{ isUploading ? '上传中...' : '上传参考音频' }}
      </button>
      <button
        :class="[
          'px-4 py-2 rounded-lg text-sm transition-colors',
          isRecording
            ? 'bg-destructive text-destructive-foreground'
            : 'bg-secondary text-secondary-foreground hover:bg-accent'
        ]"
        @click="toggleRecording"
        :disabled="isUploading"
      >
        {{ isRecording ? '● 停止录音' : '🎤 录制参考音频' }}
      </button>
      <input
        ref="fileInput"
        type="file"
        accept="audio/*"
        class="hidden"
        @change="onFileSelected"
      />
      <span class="text-xs text-muted-foreground">
        支持 wav/mp3/m4a/ogg/flac/webm，建议 5-15 秒干净人声
      </span>
    </div>

    <!-- 录音提示: 让用户照着念 -->
    <div
      :class="[
        'p-3 rounded-lg border-2 transition-colors',
        isRecording
          ? 'border-destructive bg-destructive/10'
          : 'border-primary/30 bg-primary/5'
      ]"
    >
      <div class="flex items-center gap-2 text-sm font-medium mb-2">
        <span :class="isRecording ? 'text-destructive' : 'text-primary'">
          {{ isRecording ? '🎙️ 正在录音 — 请照着念' : '📢 录音时照着念（ref_text）' }}
        </span>
      </div>
      <p class="text-base leading-relaxed font-medium select-none">
        {{ RECORDING_PROMPT }}
      </p>
      <p class="text-xs text-muted-foreground mt-2">
        ⚠ 录出来的内容必须与上方文本<strong>一字不差</strong>，F5-TTS 会基于文本和音频对齐韵律
      </p>
    </div>

    <!-- ref_text 输入 -->
    <div class="space-y-1">
      <label class="text-sm font-medium">参考文本 (ref_text)</label>
      <div class="flex gap-2">
        <input
          v-model="refTextInput"
          type="text"
          placeholder="参考音频里实际说的话（一字不差）"
          class="flex-1 px-3 py-2 bg-background border border-border rounded-lg text-sm"
        />
        <button
          class="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 text-sm whitespace-nowrap"
          @click="saveRefText"
          :disabled="!refTextInput.trim()"
        >
          保存
        </button>
      </div>
      <p class="text-xs text-muted-foreground">F5-TTS 必须一字不差匹配参考音频内容，否则克隆效果差。</p>
    </div>

    <!-- 试听 / 试合成 / 删除 -->
    <div v-if="refInfo?.exists" class="flex items-center gap-2 flex-wrap">
      <audio
        v-if="status?.ref_exists"
        :src="api.refAudioUrl()"
        controls
        class="h-8"
      />

      <div class="flex items-center gap-2 ml-auto">
        <input
          v-model="testText"
          type="text"
          class="px-3 py-1 bg-background border border-border rounded text-sm w-48"
          placeholder="测试文本"
        />
        <button
          class="px-3 py-1 bg-secondary text-secondary-foreground rounded hover:bg-accent text-sm"
          @click="testSynthesize"
          :disabled="isSynthesizing || !isAvailable"
        >
          {{ isSynthesizing ? '合成中...' : '🎵 试合成' }}
        </button>
        <button
          class="px-3 py-1 text-destructive hover:bg-destructive/10 rounded text-sm"
          @click="deleteRef"
        >
          删除
        </button>
      </div>
    </div>

    <!-- 试合成结果 -->
    <div v-if="testAudioUrl" class="p-3 rounded-lg bg-background/50 border border-border">
      <div class="text-sm font-medium mb-2">试合成结果</div>
      <audio :src="testAudioUrl" controls class="w-full" />
    </div>

    <!-- 错误提示 -->
    <div v-if="uploadError" class="text-sm text-destructive p-2 bg-destructive/10 rounded">
      {{ uploadError }}
    </div>
    <div v-if="store.lastError" class="text-sm text-destructive p-2 bg-destructive/10 rounded">
      {{ store.lastError }}
    </div>
  </div>
</template>