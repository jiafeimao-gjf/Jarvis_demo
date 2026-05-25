<script setup lang="ts">
import { useHardwareStore } from '@/stores/hardware'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { cn } from '@/lib/utils'

const hardware = useHardwareStore()
const speech = useSpeechRecognition()

function toggleMic() {
  speech.toggle()
}
</script>

<template>
  <header class="h-14 bg-secondary border-b border-border flex items-center justify-between px-6">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
        <span class="text-lg font-bold text-primary-foreground">J</span>
      </div>
      <h1 class="text-lg font-semibold">贾维斯</h1>
    </div>

    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.system.server ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        服务器
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.system.ollama ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        Ollama
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.hardware.microphone ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        麦克风
      </div>

      <div class="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            hardware.hardware.camera ? 'bg-green-500' : 'bg-red-500'
          ]"
        />
        摄像头
      </div>
    </div>
  </header>
</template>