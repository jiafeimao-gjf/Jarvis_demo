<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useSkillsStore } from '@/stores/skills'
import type { Skill } from '@/types'

const store = useSkillsStore()

// ── Tabs ────────────────────────────────────────────────────────────────────
const activeTab = ref<'list' | 'tags' | 'groups'>('list')

// ── Filters & search ────────────────────────────────────────────────────────
const searchQuery = ref('')
const filterTag = ref<string | null>(null)
const filterGroup = ref<string | null>(null)
const showOnlyEnabled = ref(false)

const filteredSkills = computed(() => {
  let list = store.skills
  if (filterTag.value) list = list.filter(s => s.tags.includes(filterTag.value!))
  if (filterGroup.value) list = list.filter(s => s.groups.includes(filterGroup.value!))
  if (showOnlyEnabled.value) list = list.filter(s => s.enabled)
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(s =>
      s.id.includes(q) ||
      s.name.toLowerCase().includes(q) ||
      s.description.toLowerCase().includes(q)
    )
  }
  return [...list].sort((a, b) => a.order - b.order)
})

// ── Form (create/edit modal) ────────────────────────────────────────────────
const showForm = ref(false)
const editingId = ref<string | null>(null)
const form = ref<{
  id: string
  name: string
  description: string
  content: string
  tagsInput: string
  groups: string[]
  enabled: boolean
}>({
  id: '',
  name: '',
  description: '',
  content: '',
  tagsInput: '',
  groups: ['default'],
  enabled: true,
})
const formError = ref('')
const formMessage = ref('')

function resetForm() {
  form.value = {
    id: '',
    name: '',
    description: '',
    content: '',
    tagsInput: '',
    groups: ['default'],
    enabled: true,
  }
  editingId.value = null
  formError.value = ''
  formMessage.value = ''
}

function openCreate() {
  resetForm()
  showForm.value = true
}

function openEdit(skill: Skill) {
  editingId.value = skill.id
  form.value = {
    id: skill.id,
    name: skill.name,
    description: skill.description,
    content: skill.content,
    tagsInput: skill.tags.join(', '),
    groups: [...skill.groups],
    enabled: skill.enabled,
  }
  showForm.value = true
}

function toggleGroup(g: string) {
  const idx = form.value.groups.indexOf(g)
  if (idx >= 0) form.value.groups.splice(idx, 1)
  else form.value.groups.push(g)
}

async function saveSkill() {
  formError.value = ''
  if (!form.value.id.trim()) {
    formError.value = 'ID 不能为空'
    return
  }
  if (!/^[a-z0-9][a-z0-9_-]*[a-z0-9]$/.test(form.value.id) || form.value.id.length < 3 || form.value.id.length > 64) {
    formError.value = 'ID 必须为 kebab-case (3-64 字符, 小写字母数字 + - + _)'
    return
  }
  const tags = form.value.tagsInput.split(',').map(s => s.trim()).filter(Boolean)
  const groups = form.value.groups.length > 0 ? form.value.groups : ['default']

  const payload: Partial<Skill> = {
    name: form.value.name.trim() || form.value.id,
    description: form.value.description.trim() || '(无描述)',
    content: form.value.content,
    tags,
    groups,
    enabled: form.value.enabled,
  }

  let result: { success: boolean; error?: string }
  if (editingId.value) {
    result = await store.updateSkill(editingId.value, payload)
  } else {
    result = await store.addSkill({ id: form.value.id.trim(), ...payload })
  }

  if (result.success) {
    showForm.value = false
    resetForm()
    showMessage(editingId.value ? '已更新' : '已创建')
  } else {
    formError.value = result.error || '保存失败'
  }
}

async function removeSkill(id: string) {
  if (!confirm(`确定删除 Skill "${id}"? 这会同时删除磁盘文件。`)) return
  const result = await store.removeSkill(id)
  if (result.success) showMessage('已删除')
}

// ── Markdown preview (in form) ──────────────────────────────────────────────
const previewHtml = computed(() => {
  marked.setOptions({ breaks: true, gfm: true })
  const ALLOWED_TAGS = ['p','br','strong','em','del','s','code','pre','ul','ol','li','blockquote','a','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td','hr','img','span','div']
  const ALLOWED_ATTR = ['href','target','src','alt','class','id']
  const raw = marked.parse(form.value.content || '') as string
  return DOMPurify.sanitize(raw, { ALLOWED_TAGS, ALLOWED_ATTR })
})

// ── Active groups editor ───────────────────────────────────────────────────
const activeGroupsSelection = ref<Set<string>>(new Set())

function syncActiveGroupsSelection() {
  activeGroupsSelection.value = new Set(store.config.active_groups)
}

function toggleActiveGroup(g: string) {
  if (activeGroupsSelection.value.has(g)) {
    activeGroupsSelection.value.delete(g)
  } else {
    activeGroupsSelection.value.add(g)
  }
}

async function applyActiveGroups() {
  const groups = Array.from(activeGroupsSelection.value)
  if (groups.length === 0) {
    showMessage('至少选择一个分组')
    return
  }
  await store.setActiveGroups(groups)
  showMessage('已更新激活分组')
}

// ── Tag/Group rename/delete ─────────────────────────────────────────────────
const renameTarget = ref<{ kind: 'tag' | 'group'; old: string; newName: string } | null>(null)

function startRename(kind: 'tag' | 'group', old: string) {
  renameTarget.value = { kind, old, newName: old }
}

async function applyRename() {
  if (!renameTarget.value) return
  const { kind, old, newName } = renameTarget.value
  if (!newName.trim() || newName === old) {
    renameTarget.value = null
    return
  }
  let ok = false
  if (kind === 'tag') ok = await store.renameTag(old, newName.trim())
  else ok = await store.renameGroup(old, newName.trim())
  renameTarget.value = null
  if (ok) showMessage('已重命名')
}

async function deleteTag(name: string) {
  if (!confirm(`删除标签 "${name}"? (会从所有 skill 中移除)`)) return
  await store.deleteTag(name)
  if (filterTag.value === name) filterTag.value = null
  showMessage('已删除标签')
}

async function deleteGroup(name: string) {
  if (name === 'default') {
    showMessage('默认分组不可删除')
    return
  }
  if (!confirm(`删除分组 "${name}"? (使用该分组的 skill 会回到 default)`)) return
  await store.deleteGroup(name)
  if (filterGroup.value === name) filterGroup.value = null
  showMessage('已删除分组')
}

// ── Refresh from disk ───────────────────────────────────────────────────────
async function refreshDisk() {
  await store.refreshFromDisk()
  syncActiveGroupsSelection()
  showMessage('已刷新磁盘')
}

// ── Toast ───────────────────────────────────────────────────────────────────
const message = ref('')
let messageTimer: ReturnType<typeof setTimeout> | null = null
function showMessage(msg: string) {
  message.value = msg
  if (messageTimer) clearTimeout(messageTimer)
  messageTimer = setTimeout(() => { message.value = '' }, 3000)
}

// ── Lifecycle ───────────────────────────────────────────────────────────────
onMounted(async () => {
  await store.loadFromBackend()
  syncActiveGroupsSelection()
})
</script>

<template>
  <div class="space-y-4">
    <!-- Tabs + actions -->
    <div class="flex items-center gap-2 border-b border-border pb-2">
      <button
        v-for="t in (['list','tags','groups'] as const)"
        :key="t"
        class="px-3 py-1 text-sm rounded-t"
        :class="activeTab === t ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'"
        @click="activeTab = t"
      >
        {{ t === 'list' ? '技能列表' : t === 'tags' ? '标签管理' : '分组管理' }}
      </button>

      <div class="flex-1" />

      <button
        class="px-2 py-1 text-xs rounded hover:bg-accent"
        :disabled="store.isSyncing"
        @click="refreshDisk"
      >
        {{ store.isSyncing ? '刷新中…' : '🔄 从磁盘刷新' }}
      </button>

      <button
        v-if="activeTab === 'list'"
        class="px-3 py-1 bg-primary text-primary-foreground rounded text-sm hover:opacity-90"
        @click="openCreate"
      >
        + 新建 Skill
      </button>
    </div>

    <!-- ══════════════ List Tab ══════════════ -->
    <div v-if="activeTab === 'list'" class="space-y-3">
      <!-- Filters -->
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="searchQuery"
          placeholder="搜索 ID / 名称 / 描述"
          class="flex-1 min-w-[160px] bg-background rounded px-2 py-1 border border-border text-sm"
        />
        <select v-model="filterTag" class="bg-background rounded px-2 py-1 border border-border text-sm">
          <option :value="null">所有标签</option>
          <option v-for="t in store.tags" :key="t.name" :value="t.name">{{ t.name }} ({{ t.skill_count }})</option>
        </select>
        <select v-model="filterGroup" class="bg-background rounded px-2 py-1 border border-border text-sm">
          <option :value="null">所有分组</option>
          <option v-for="g in store.groups" :key="g.name" :value="g.name">
            {{ g.name }} ({{ g.skill_count }}){{ g.is_active ? ' ✓' : '' }}
          </option>
        </select>
        <label class="flex items-center gap-1 text-xs text-muted-foreground">
          <input v-model="showOnlyEnabled" type="checkbox" />
          仅显示启用
        </label>
        <span class="text-xs text-muted-foreground">
          {{ filteredSkills.length }} / {{ store.skills.length }}
        </span>
      </div>

      <!-- Skill list -->
      <div v-if="filteredSkills.length === 0" class="text-sm text-muted-foreground text-center py-6">
        {{ store.skills.length === 0 ? '暂无 Skill — 点击右上「+ 新建」开始' : '没有匹配的 Skill' }}
      </div>

      <div
        v-for="skill in filteredSkills"
        :key="skill.id"
        class="flex items-start gap-3 p-3 bg-background rounded-lg border border-border"
        :class="{ 'opacity-50': !skill.enabled || skill.missing }"
      >
        <!-- Enable toggle -->
        <button
          class="w-9 h-5 rounded-full flex-shrink-0 mt-1 transition-colors"
          :class="skill.enabled ? 'bg-green-500' : 'bg-gray-600'"
          :title="skill.enabled ? '已启用 — 点击停用' : '已停用 — 点击启用'"
          @click="store.toggleSkill(skill.id)"
        >
          <span
            class="block w-3.5 h-3.5 rounded-full bg-white transform transition-transform mt-[3px]"
            :class="skill.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'"
          />
        </button>

        <!-- Info -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-sm font-medium">{{ skill.name }}</span>
            <span class="text-xs text-muted-foreground font-mono">{{ skill.id }}</span>
            <span v-if="skill.missing" class="text-xs bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">
              文件缺失
            </span>
          </div>
          <div class="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {{ skill.description }}
          </div>
          <div class="flex flex-wrap items-center gap-1 mt-1.5">
            <span
              v-for="tag in skill.tags"
              :key="tag"
              class="text-xs bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded"
            >
              #{{ tag }}
            </span>
            <span
              v-for="g in skill.groups"
              :key="g"
              class="text-xs px-1.5 py-0.5 rounded"
              :class="store.config.active_groups.includes(g) ? 'bg-green-500/15 text-green-400' : 'bg-purple-500/15 text-purple-400'"
            >
              {{ g }}
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-1 flex-shrink-0">
          <button
            class="px-2 py-1 text-xs rounded hover:bg-accent"
            @click="openEdit(skill)"
          >
            编辑
          </button>
          <button
            class="px-2 py-1 text-xs text-red-400 rounded hover:bg-red-500/10"
            @click="removeSkill(skill.id)"
          >
            删除
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════ Tags Tab ══════════════ -->
    <div v-if="activeTab === 'tags'" class="space-y-2">
      <div v-if="store.tags.length === 0" class="text-sm text-muted-foreground text-center py-6">
        暂无标签
      </div>
      <div
        v-for="tag in store.tags"
        :key="tag.name"
        class="flex items-center gap-3 p-2 bg-background rounded border border-border"
      >
        <span class="text-sm font-medium flex-1">#{{ tag.name }}</span>
        <span class="text-xs text-muted-foreground">{{ tag.skill_count }} 个 skill</span>
        <template v-if="renameTarget?.kind === 'tag' && renameTarget.old === tag.name">
          <input
            v-model="renameTarget.newName"
            class="bg-background rounded px-2 py-1 border border-border text-sm"
            @keyup.enter="applyRename"
            @keyup.escape="renameTarget = null"
          />
          <button class="px-2 py-1 text-xs bg-primary text-primary-foreground rounded" @click="applyRename">保存</button>
          <button class="px-2 py-1 text-xs rounded hover:bg-accent" @click="renameTarget = null">取消</button>
        </template>
        <template v-else>
          <button class="px-2 py-1 text-xs rounded hover:bg-accent" @click="startRename('tag', tag.name)">重命名</button>
          <button class="px-2 py-1 text-xs text-red-400 rounded hover:bg-red-500/10" @click="deleteTag(tag.name)">删除</button>
        </template>
      </div>
    </div>

    <!-- ══════════════ Groups Tab ══════════════ -->
    <div v-if="activeTab === 'groups'" class="space-y-3">
      <!-- Active groups selector -->
      <div class="bg-background rounded p-3 border border-border">
        <div class="text-sm font-medium mb-2">激活分组 (chat system prompt 只注入 active groups)</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="g in store.groups"
            :key="g.name"
            class="px-2 py-1 text-xs rounded border"
            :class="activeGroupsSelection.has(g.name)
              ? 'bg-primary text-primary-foreground border-primary'
              : 'border-border hover:bg-accent'"
            @click="toggleActiveGroup(g.name)"
          >
            {{ g.name }} ({{ g.skill_count }})
          </button>
        </div>
        <button
          class="mt-2 px-3 py-1 text-sm bg-primary text-primary-foreground rounded hover:opacity-90"
          @click="applyActiveGroups"
        >
          应用
        </button>
      </div>

      <!-- Group list -->
      <div v-if="store.groups.length === 0" class="text-sm text-muted-foreground text-center py-6">
        暂无分组
      </div>
      <div
        v-for="g in store.groups"
        :key="g.name"
        class="flex items-center gap-3 p-2 bg-background rounded border border-border"
      >
        <span
          class="w-2 h-2 rounded-full"
          :class="g.is_active ? 'bg-green-400' : 'bg-gray-500'"
        />
        <span class="text-sm font-medium flex-1">{{ g.name }}</span>
        <span class="text-xs text-muted-foreground">{{ g.skill_count }} 个 skill</span>
        <span class="text-xs" :class="g.is_active ? 'text-green-400' : 'text-gray-500'">
          {{ g.is_active ? '已激活' : '未激活' }}
        </span>
        <template v-if="renameTarget?.kind === 'group' && renameTarget.old === g.name">
          <input
            v-model="renameTarget.newName"
            class="bg-background rounded px-2 py-1 border border-border text-sm"
            @keyup.enter="applyRename"
            @keyup.escape="renameTarget = null"
          />
          <button class="px-2 py-1 text-xs bg-primary text-primary-foreground rounded" @click="applyRename">保存</button>
          <button class="px-2 py-1 text-xs rounded hover:bg-accent" @click="renameTarget = null">取消</button>
        </template>
        <template v-else>
          <button
            class="px-2 py-1 text-xs rounded hover:bg-accent"
            :disabled="g.name === 'default'"
            @click="startRename('group', g.name)"
          >重命名</button>
          <button
            class="px-2 py-1 text-xs text-red-400 rounded hover:bg-red-500/10"
            :disabled="g.name === 'default'"
            @click="deleteGroup(g.name)"
          >删除</button>
        </template>
      </div>
    </div>

    <!-- Error / Toast -->
    <div v-if="store.errorMessage" class="text-xs text-red-400 bg-red-500/10 rounded p-2">
      {{ store.errorMessage }}
    </div>
    <div v-if="message" class="text-xs text-green-400 bg-green-500/10 rounded p-2">
      {{ message }}
    </div>

    <!-- ══════════════ Create/Edit Modal ══════════════ -->
    <Teleport to="body">
      <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div class="bg-background border border-border rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col shadow-xl">
          <div class="flex items-center justify-between p-4 border-b border-border">
            <h3 class="text-lg font-semibold">
              {{ editingId ? `编辑 Skill: ${editingId}` : '新建 Skill' }}
            </h3>
            <button class="text-muted-foreground hover:text-foreground" @click="showForm = false">✕</button>
          </div>

          <div class="flex-1 overflow-y-auto p-4 space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs mb-1 text-muted-foreground">ID (唯一, kebab-case)</label>
                <input
                  v-model="form.id"
                  :disabled="!!editingId"
                  class="w-full bg-background rounded px-3 py-2 border border-border text-sm font-mono"
                  placeholder="如 my-skill"
                />
              </div>
              <div>
                <label class="block text-xs mb-1 text-muted-foreground">显示名称</label>
                <input
                  v-model="form.name"
                  class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                  placeholder="如 My Skill"
                />
              </div>
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">描述 (用于 system prompt 简述)</label>
              <input
                v-model="form.description"
                class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                placeholder="一句话描述此 skill 的能力"
              />
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs mb-1 text-muted-foreground">标签 (逗号分隔, 用于筛选)</label>
                <input
                  v-model="form.tagsInput"
                  class="w-full bg-background rounded px-3 py-2 border border-border text-sm"
                  placeholder="如: demo, test"
                />
              </div>
              <div>
                <label class="block text-xs mb-1 text-muted-foreground">分组 (点击切换)</label>
                <div class="flex flex-wrap gap-1 p-2 bg-background rounded border border-border min-h-[38px]">
                  <button
                    v-for="g in store.groups"
                    :key="g.name"
                    class="px-2 py-0.5 text-xs rounded border"
                    :class="form.groups.includes(g.name)
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border hover:bg-accent'"
                    @click="toggleGroup(g.name)"
                  >
                    {{ g.name }}
                  </button>
                  <span v-if="store.groups.length === 0" class="text-xs text-muted-foreground">暂无分组</span>
                </div>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <input v-model="form.enabled" type="checkbox" id="skill-enabled" class="w-4 h-4" />
              <label for="skill-enabled" class="text-sm">启用 (停用后不会注入到 system prompt)</label>
            </div>

            <div>
              <label class="block text-xs mb-1 text-muted-foreground">Markdown Body (含代码示例、使用方法等)</label>
              <div class="grid grid-cols-2 gap-2">
                <textarea
                  v-model="form.content"
                  rows="14"
                  class="w-full bg-background rounded px-3 py-2 border border-border text-sm font-mono"
                  placeholder="# 标题&#10;&#10;说明文字..."
                />
                <div
                  class="w-full bg-background rounded px-3 py-2 border border-border text-sm overflow-y-auto"
                  style="max-height: 320px"
                  v-html="previewHtml"
                />
              </div>
            </div>

            <p v-if="formError" class="text-xs text-red-400">{{ formError }}</p>
          </div>

          <div class="flex justify-end gap-2 p-4 border-t border-border">
            <button class="px-4 py-2 rounded hover:bg-accent text-sm" @click="showForm = false">取消</button>
            <button
              class="px-4 py-2 bg-primary text-primary-foreground rounded hover:opacity-90 text-sm"
              @click="saveSkill"
            >
              {{ editingId ? '保存' : '创建' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
:deep(pre) {
  background: rgba(0,0,0,0.3);
  padding: 0.5rem;
  border-radius: 4px;
  overflow-x: auto;
}
:deep(code) {
  background: rgba(0,0,0,0.2);
  padding: 0 0.25rem;
  border-radius: 3px;
  font-size: 0.875em;
}
:deep(pre code) {
  background: transparent;
  padding: 0;
}
</style>
