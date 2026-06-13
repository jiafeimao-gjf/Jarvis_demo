<script setup lang="ts">
import { ref } from 'vue'
import { useHardwareStore } from '@/stores/hardware'
import { useProvidersStore } from '@/stores/providers'
import Notification from './Notification.vue'

const hardware = useHardwareStore()
const providersStore = useProvidersStore()
const showSwitcher = ref(false)

const emit = defineEmits<{
  (e: 'open-settings'): void
}>()

function openSettings() {
  emit('open-settings')
}

function selectInstance(id: string) {
  providersStore.setActive(id)
  showSwitcher.value = false
}
</script>

<template>
  <header class="h-14 scifi-panel flex items-center justify-between px-6 relative overflow-hidden">
    <div class="absolute inset-0 cyber-grid opacity-50 pointer-events-none" />

    <div class="flex items-center gap-4 relative z-10">
      <div class="w-10 h-10 rounded-lg bg-background border border-primary/50 flex items-center justify-center glow-primary">
        <span class="text-lg font-bold text-primary text-glow">J</span>
      </div>

      <h1 class="text-lg font-semibold tracking-wide text-glow">JARVIS</h1>
    </div>

    <div class="flex items-center gap-6 relative z-10">
      <div class="flex items-center gap-2 text-sm">
        <span
          :class="[
            'w-2.5 h-2.5 rounded-full transition-all',
            hardware.system.server
              ? 'bg-green-400 pulse-glow text-green-400'
              : 'bg-red-500/70'
          ]"
        />
        <span :class="hardware.system.server ? 'text-green-400' : 'text-muted-foreground'">SERVER</span>
      </div>

      <div class="flex items-center gap-2 text-sm">
        <span
          :class="[
            'w-2.5 h-2.5 rounded-full transition-all',
            hardware.system.ollama
              ? 'bg-cyan-400 pulse-glow text-cyan-400'
              : 'bg-red-500/70'
          ]"
        />
        <span :class="hardware.system.ollama ? 'text-cyan-400' : 'text-muted-foreground'">OLLAMA</span>
      </div>

      <div class="flex items-center gap-2 text-sm">
        <span
          :class="[
            'w-2.5 h-2.5 rounded-full transition-all',
            hardware.hardware.microphone
              ? 'bg-green-400 pulse-glow text-green-400'
              : 'bg-red-500/70'
          ]"
        />
        <span :class="hardware.hardware.microphone ? 'text-green-400' : 'text-muted-foreground'">MIC</span>
      </div>

      <div class="flex items-center gap-2 text-sm">
        <span
          :class="[
            'w-2.5 h-2.5 rounded-full transition-all',
            hardware.hardware.camera
              ? 'bg-green-400 pulse-glow text-green-400'
              : 'bg-red-500/70'
          ]"
        />
        <span :class="hardware.hardware.camera ? 'text-green-400' : 'text-muted-foreground'">CAM</span>
      </div>

      <!-- Provider switcher -->
      <div v-if="providersStore.activeInstance" class="relative">
        <button
          class="flex items-center gap-2 text-sm hover:bg-accent/50 rounded-lg px-2 py-1 transition-all"
          @click="showSwitcher = !showSwitcher"
        >
          <span class="w-2.5 h-2.5 rounded-full bg-cyan-400 pulse-glow" />
          <span class="text-cyan-400 max-w-24 truncate">{{ providersStore.activeInstance.display_name || providersStore.activeInstance.id }}</span>
          <svg class="w-3.5 h-3.5 text-cyan-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
          </svg>
        </button>

        <Teleport to="body">
          <div v-if="showSwitcher" class="fixed inset-0 z-50" @click="showSwitcher = false">
            <div class="absolute right-6 top-14 w-72 bg-background border border-border rounded-lg shadow-xl p-2">
              <div class="text-xs text-muted-foreground px-3 py-1 mb-1">切换 Provider</div>
              <div
                v-for="inst in providersStore.instances.filter((i: any) => i.enabled)"
                :key="inst.id"
                class="px-3 py-2 rounded hover:bg-accent cursor-pointer flex justify-between items-center"
                :class="inst.id === providersStore.activeProviderId ? 'bg-primary/10' : ''"
                @click.stop="selectInstance(inst.id)"
              >
                <div>
                  <div class="text-sm">{{ inst.display_name || inst.id }}</div>
                  <div class="text-xs text-muted-foreground">{{ inst.default_model }}</div>
                </div>
                <svg v-if="inst.id === providersStore.activeProviderId" class="w-4 h-4 text-primary flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
                </svg>
              </div>
            </div>
          </div>
        </Teleport>
      </div>

      <Notification />

      <button
        class="p-2 hover:bg-accent/50 rounded-lg transition-all btn-cyber"
        @click="openSettings"
        title="设置"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>
  </header>
</template>