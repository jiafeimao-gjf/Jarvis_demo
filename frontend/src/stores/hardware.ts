import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { HardwareStatus, SystemStatus } from '@/types'

export const useHardwareStore = defineStore('hardware', () => {
  const hardware = ref<HardwareStatus>({
    camera: false,
    microphone: false
  })

  const system = ref<SystemStatus>({
    server: false,
    ollama: false
  })

  const cameraStream = ref<MediaStream | null>(null)
  const microphoneStream = ref<MediaStream | null>(null)

  async function toggleCamera() {
    if (hardware.value.camera) {
      stopCamera()
    } else {
      await startCamera()
    }
  }

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      cameraStream.value = stream
      hardware.value.camera = true
    } catch (e) {
      console.error('Camera access denied:', e)
      throw e
    }
  }

  function stopCamera() {
    cameraStream.value?.getTracks().forEach(track => track.stop())
    cameraStream.value = null
    hardware.value.camera = false
  }

  async function toggleMicrophone() {
    if (hardware.value.microphone) {
      stopMicrophone()
    } else {
      await startMicrophone()
    }
  }

  async function startMicrophone() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      microphoneStream.value = stream
      hardware.value.microphone = true
    } catch (e) {
      console.error('Microphone access denied:', e)
      throw e
    }
  }

  function stopMicrophone() {
    microphoneStream.value?.getTracks().forEach(track => track.stop())
    microphoneStream.value = null
    hardware.value.microphone = false
  }

  function updateSystemStatus(status: Partial<SystemStatus>) {
    Object.assign(system.value, status)
  }

  return {
    hardware,
    system,
    cameraStream,
    microphoneStream,
    toggleCamera,
    startCamera,
    stopCamera,
    toggleMicrophone,
    startMicrophone,
    stopMicrophone,
    updateSystemStatus
  }
})