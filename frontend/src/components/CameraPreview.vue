<script setup lang="ts">
import { useHardwareStore } from '@/stores/hardware'

const hardware = useHardwareStore()

function handleClose() {
  hardware.stopCamera()
}
</script>

<template>
  <Transition
    enter-active-class="transition duration-300 ease-out"
    enter-from-class="opacity-0 scale-95"
    enter-to-class="opacity-100 scale-100"
    leave-active-class="transition duration-300 ease-in"
    leave-from-class="opacity-100 scale-100"
    leave-to-class="opacity-0 scale-95"
  >
    <div
      v-if="hardware.hardware.camera && hardware.cameraStream"
      class="fixed bottom-20 right-6 w-64 h-48 rounded-xl border-2 border-primary overflow-hidden shadow-2xl bg-secondary z-50"
    >
      <video
        :srcObject="hardware.cameraStream"
        autoplay
        playsinline
        muted
        class="w-full h-full object-cover"
      />
      <button
        class="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-black/90 transition-colors"
        @click="handleClose"
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
      <div class="absolute bottom-2 left-2 text-xs text-white bg-black/50 px-2 py-1 rounded">
        摄像头已开启
      </div>
    </div>
  </Transition>
</template>