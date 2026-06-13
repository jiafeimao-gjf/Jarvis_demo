<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useProvidersStore } from '@/stores/providers'
import type { ProviderInstance, ProviderType } from '@/types'

const store = useProvidersStore()

const showForm = ref(false)
const editingId = ref<string | null>(null)
const testResult = ref<{ ok: boolean; latency_ms?: number; error?: string } | null>(null)
const testLoading = ref<string | null>(null)
const message = ref('')

const form = ref<ProviderInstance>({
  id: '',
  type: 'ollama',
  display_name: '',
  base_url: '',
  default_model: '',
  enabled: true,
  timeout: 60,
})

const providerModels = ref<Record<ProviderType, string[]>>({
  ollama: ['qwen3:4b', 'qwen3:8b', 'qwen3.5:9b', 'llama3:8b'],
  openai: ['gpt-4o-mini', 'gpt-4o'],
  anthropic: ['claude-3-haiku', 'claude-3-5-sonnet'],
  minimax: ['MiniMax-M2.7-highspeed', 'abab6.5s-chat'],
})

function resetForm() {
  form.value = {
    id: '',
    type: 'ollama',
    display_name: '',
    base_url: 'http://localhost:11434',
    default_model: 'qwen3:4b',
    enabled: true,
    timeout: 60,
  }
  editingId.value = null
  testResult.value = null
}

function openAdd() {
  resetForm()
  showForm.value = true
}

function openEdit(inst: ProviderInstance) {
  editingId.value = inst.id
  form.value = { ...inst }
  testResult.value = null
  showForm.value = true
}

async function saveInstance() {
  message.value = ''
  if (!form.value.id.trim()) {
    message.value = 'ID 不能为空'
    return
  }
  if (!form.value.display_name.trim()) {
    message.value = '显示名称不能为空'
    return
  }
  if (form.value.type === 'ollama' && !form.value.base_url) {
    message.value = 'Ollama 必须填写服务器地址'
    return
  }

  const inst: ProviderInstance = { ...form.value }
  let result: { success: boolean; error?: string }

  if (editingId.value) {
    result = await store.updateInstance(editingId.value, inst)
  } else {
    result = await store.addInstance(inst)
  }

  if (result.success) {
    showForm.value = false
    resetForm()
    showMessage(editingId.value ? '已更新' : '已添加')
  } else {
    message.value = result.error || '保存失败'
  }
}

async function deleteInstance(id: string) {
  if (!confirm('确定删除此 Provider？')) return
  await store.removeInstance(id)
  showMessage('已删除')
}

async function setActive(id: string) {
  await store.setActive(id)
  showMessage('已设为默认')
}

async function testInstance(id: string) {
  testLoading.value = id
  testResult.value = null
  try {
    testResult.value = await store.testInstance(id)
  } finally {
    testLoading.value = null
  }
}

function showMessage(msg: string) {
  message.value = msg
  setTimeout(() => { message.value = '' }, 3000)
}

onMounted(async () => {
  await store.loadFromBackend()
  await store.loadActive()
})
</script>

<template>
  <div class="space-y-4">
    <!-- Header: list + add button -->
    <div class="flex items-center justify-between">
      <div class="text-sm text-muted-foreground">
        共 {{ store.instances.length }} 个配置
      </div>
      <button
        class="px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 text-sm"
        @click="openAdd"
      >
        + 新增 Provider
      </button>
    </div>

    <!-- Instances table -->
    <div v-if="store.instances.length > 0" class="space-y-2">
      <div
        v-for="inst in store.instances"
        :key="inst.id"
        class="flex items-center gap-3 p-3 bg-background rounded-lg border border-border"
      >
        <!-- Active badge -->
        <span v-if="inst.id === store.activeProviderId" class="text-xs bg-primary/20 text-primary px-1.5 py-0.5 rounded">
          默认
        </span>

        <!-- Type icon -->
        <span class="w-8 h-8 rounded flex items-center justify-center text-xs font-bold"
              :class="{
                'bg-blue-500/20 text-blue-400': inst.type === 'ollama',
                'bg-green-500/20 text-green-400': inst.type === 'openai',
                'bg-orange-500/20 text-orange-400': inst.type === 'anthropic',
              }">
          {{ inst.type === 'ollama' ? 'O' : inst.type === 'openai' ? 'G' : 'A' }}
        </span>

        <!-- Info -->
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate">{{ inst.display_name || inst.id }}</div>
          <div class="text-xs text-muted-foreground truncate">
            {{ inst.base_url || inst.api_key ? (inst.base_url || '***') : '—' }}
            · {{ inst.default_model }}
          </div>
        </div>

        <!-- Status dot -->
        <span class="w-2.5 h-2.5 rounded-full flex-shrink-0"
              :class="inst.enabled ? 'bg-green-400' : 'bg-gray-600'" />

        <!-- Actions -->
        <div class="flex items-center gap-1">
          <button
            v-if="inst.id !== store.activeProviderId"
            class="px-2 py-1 text-xs rounded hover:bg-accent"
            @click="setActive(inst.id)"
            title="设为默认"
          >
            设为默认
          </button>
          <button
            class="px-2 py-1 text-xs rounded hover:bg-accent"
            @click="testInstance(inst.id)"
            :disabled="testLoading === inst.id"
            title="测试连接"
          >
            {{ testLoading === inst.id ? '测试中...' : '测试' }}
          </button>
          <button
            class="px-2 py-1 text-xs rounded hover:bg-accent"
            @click="openEdit(inst)"
          >
            编辑
          </button>
          <button
            class="px-2 py-1 text-xs text-red-400 rounded hover:bg-red-500/10"
            @click="deleteInstance(inst.id)"
          >
            删除
          </button>
        </div>
      </div>

      <!-- Test result -->
      <div v-if="testResult" class="text-xs px-3 py-2 rounded"
           :class="testResult.ok ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'">
        {{ testResult.ok ? `✓ 连接成功 (${testResult.latency_ms}ms)` : `✗ ${testResult.error}` }}
      </div>
    </div>

    <div v-else class="text-sm text-muted-foreground text-center py-4">
      暂无 Provider 配置
    </div>

    <!-- Form overlay -->
    <Teleport to="body">
      <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div class="bg-background border border-border rounded-lg w-full max-w-md p-6 shadow-xl">
          <h3 class="text-lg font-semibold mb-4">
            {{ editingId ? '编辑 Provider' : '新增 Provider' }}
          </h3>

          <div class="space-y-3">
            <div>
              <label class="block text-xs mb-1 text-muted-foreground">技术 ID（唯一标识）</label>
              <input
                v-model="form.id"
                :disabled="!!editingId"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="如 ollama-local"
              />
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">显示名称</label>
              <input
                v-model="form.display_name"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="如 本地 Ollama"
              />
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">类型</label>
              <select
                v-model="form.type"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
              >
                <option value="ollama">Ollama (本地)</option>
                <option value="openai">OpenAI (云端)</option>
                <option value="anthropic">Anthropic (云端)</option>
                <option value="minimax">MiniMax (云端)</option>
              </select>
            </div>

            <div v-if="form.type === 'ollama'">
              <label class="block text-xs mb-1 text-muted-foreground">服务器地址</label>
              <input
                v-model="form.base_url"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="http://localhost:11434"
              />
            </div>

            <div v-if="form.type !== 'ollama'">
              <label class="block text-xs mb-1 text-muted-foreground">
                API Key {{ form.type === 'anthropic' ? '' : '(可选)' }}
              </label>
              <input
                v-model="form.api_key"
                type="password"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="sk-..."
              />
            </div>

            <div v-if="form.type !== 'ollama'">
              <label class="block text-xs mb-1 text-muted-foreground">Base URL (可选)</label>
              <input
                v-model="form.base_url"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                :placeholder="form.type === 'openai' ? 'https://api.openai.com/v1' : 'https://api.anthropic.com'"
              />
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">默认模型</label>
              <input
                v-model="form.default_model"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="输入或选择模型名称"
                list="model-suggestions"
              />
              <datalist id="model-suggestions">
                <option v-for="m in providerModels[form.type]" :key="m" :value="m" />
              </datalist>
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">超时 (秒)</label>
              <input
                v-model.number="form.timeout"
                type="number"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
              />
            </div>

            <div class="flex items-center gap-2">
              <input v-model="form.enabled" type="checkbox" id="inst-enabled" class="w-4 h-4" />
              <label for="inst-enabled" class="text-sm">启用</label>
            </div>
          </div>

          <p v-if="message && !message.includes('已')" class="text-xs text-red-400 mt-2">{{ message }}</p>

          <div class="flex justify-end gap-2 mt-6">
            <button class="px-4 py-2 rounded hover:bg-accent text-sm" @click="showForm = false">取消</button>
            <button
              class="px-4 py-2 bg-primary text-primary-foreground rounded hover:opacity-90 text-sm"
              @click="saveInstance"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
