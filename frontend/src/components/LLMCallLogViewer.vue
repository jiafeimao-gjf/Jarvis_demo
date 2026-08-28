<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useLLMCallLogsStore } from '@/stores/llmCallLogs'
import type { LLMCallLogSummary } from '@/types'

const store = useLLMCallLogsStore()

// ── 详情 tab 切换 ────────────────────────────────────────────────────
type DetailTab = 'request' | 'response' | 'raw_http' | 'messages'
const activeTab = ref<DetailTab>('request')

const tabs: { key: DetailTab; label: string; icon: string }[] = [
  { key: 'request', label: 'Request Body', icon: '→' },
  { key: 'response', label: 'Response', icon: '←' },
  { key: 'raw_http', label: 'Raw HTTP', icon: '⇄' },
  { key: 'messages', label: 'Messages', icon: '💬' },
]

// ── 加载 ─────────────────────────────────────────────────────────────
onMounted(async () => {
  await store.loadDates()
  await Promise.all([store.loadList(), store.loadStats()])
})

watch(() => store.selectedDate, async () => {
  activeTab.value = 'request'
  await Promise.all([store.loadList(), store.loadStats()])
})

watch(
  [
    () => store.filterConversationId,
    () => store.filterProvider,
    () => store.filterModel,
    () => store.filterStatus,
  ],
  async () => {
    store.offset = 0
    await store.loadList()
  }
)

// ── 行点击加载详情 ──────────────────────────────────────────────────
async function selectRow(item: LLMCallLogSummary) {
  activeTab.value = 'request'
  await store.loadDetail(item.call_id)
}

// ── 清空 ────────────────────────────────────────────────────────────
const showClearConfirm = ref(false)

async function confirmClear() {
  showClearConfirm.value = false
  await store.clearLogs()
}

// ── JSON 格式化（递归安全） ────────────────────────────────────────
function formatJSON(v: any): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// ── 时间格式化 ─────────────────────────────────────────────────────
function fmtTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour12: false }) +
      '.' + String(d.getMilliseconds()).padStart(3, '0')
  } catch {
    return iso
  }
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

// ── 状态颜色 ───────────────────────────────────────────────────────
function statusColor(status: string): string {
  if (status === 'success') return 'text-green-600 bg-green-50'
  if (status === 'error') return 'text-red-600 bg-red-50'
  if (status === 'stream_interrupted') return 'text-yellow-600 bg-yellow-50'
  return 'text-gray-600 bg-gray-50'
}

function statusLabel(status: string): string {
  if (status === 'success') return '✓'
  if (status === 'error') return '✗'
  if (status === 'stream_interrupted') return '⏸'
  return '·'
}

function latencyColor(ms: number): string {
  if (ms < 1000) return 'text-green-600'
  if (ms < 5000) return 'text-yellow-600'
  return 'text-red-600'
}

// ── 详情渲染辅助 ───────────────────────────────────────────────────
const detailTabContent = computed(() => {
  const d = store.selectedDetail
  if (!d) return ''
  if (activeTab.value === 'request') {
    // Request: messages + tools 摘要
    const req: any = {
      model: d.model,
      provider: d.provider,
      provider_protocol: d.provider_protocol,
      stream: d.request?.stream,
      max_tokens: d.request?.max_tokens,
      temperature: d.request?.temperature,
      messages_count: d.request?.messages?.length || 0,
      tools_count: d.request?.tools?.length || 0,
    }
    return formatJSON(req)
  }
  if (activeTab.value === 'response') {
    const resp: any = {
      content: d.response?.content,
      thinking: d.response?.thinking,
      stop_reason: d.response?.stop_reason,
      content_blocks: d.response?.content_blocks,
      usage: d.response?.usage,
      raw_summary: d.response?.raw
        ? Object.keys(d.response.raw).slice(0, 10)
        : null,
    }
    return formatJSON(resp)
  }
  if (activeTab.value === 'raw_http') {
    return formatJSON({
      request_body: d.request?.raw_http_body,
      response_body: d.response?.raw_http_body,
      stream_events_count: d.response?.raw_stream_events?.length || 0,
      stream_events_preview: d.response?.raw_stream_events?.slice(0, 5) || [],
    })
  }
  if (activeTab.value === 'messages') {
    return formatJSON(d.request?.messages || [])
  }
  return ''
})

// ── messages 单独 tab 的提取 ────────────────────────────────────────
const detailMessages = computed(() => store.selectedDetail?.request?.messages || [])
</script>

<template>
  <div class="llm-log-viewer flex h-full">
    <!-- 左侧: 列表 + 过滤 -->
    <div class="w-1/2 flex flex-col border-r border-gray-200">
      <!-- 顶部: 日期 + 过滤 + 统计 + 清空 -->
      <div class="p-3 border-b border-gray-200 bg-gray-50">
        <div class="flex items-center gap-2 mb-2">
          <label class="text-xs text-gray-600">日期:</label>
          <select
            v-model="store.selectedDate"
            class="flex-1 text-xs border border-gray-300 rounded px-2 py-1 bg-white"
          >
            <option :value="null">今天</option>
            <option v-for="d in store.dates" :key="d" :value="d">{{ d }}</option>
          </select>
          <button
            v-if="store.dates.length > 0"
            @click="showClearConfirm = true"
            class="text-xs px-2 py-1 bg-red-50 text-red-600 rounded hover:bg-red-100"
            title="清空当前日期的日志"
          >
            清空
          </button>
        </div>

        <!-- 统计摘要 -->
        <div v-if="store.stats" class="flex items-center gap-3 text-xs text-gray-600 mb-2">
          <span>共 <b class="text-gray-900">{{ store.stats.total }}</b> 次</span>
          <span :class="store.stats.error_rate > 0 ? 'text-red-600' : 'text-green-600'">
            错误率 {{ (store.stats.error_rate * 100).toFixed(1) }}%
          </span>
          <span :class="latencyColor(store.stats.latency_ms.avg)">
            avg {{ store.stats.latency_ms.avg.toFixed(0) }}ms
          </span>
          <span :class="latencyColor(store.stats.latency_ms.p95)">
            p95 {{ store.stats.latency_ms.p95.toFixed(0) }}ms
          </span>
          <span class="flex-1"></span>
          <!-- 视图模式 toggle -->
          <div class="inline-flex rounded border border-gray-300 overflow-hidden">
            <button
              @click="store.viewMode = 'time'"
              class="text-xs px-2 py-0.5 transition-colors"
              :class="store.viewMode === 'time' ? 'bg-blue-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-100'"
              title="按时间顺序平铺"
            >
              按时间
            </button>
            <button
              @click="store.viewMode = 'conversation'"
              class="text-xs px-2 py-0.5 transition-colors"
              :class="store.viewMode === 'conversation' ? 'bg-blue-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-100'"
              title="按会话分组折叠"
            >
              按会话 ({{ store.groupedByConversation.length }})
            </button>
          </div>
          <button
            v-if="store.viewMode === 'conversation'"
            @click="store.expandedGroups.size > 0 ? store.collapseAllGroups() : store.expandAllGroups()"
            class="text-xs px-1.5 py-0.5 bg-white border border-gray-300 rounded hover:bg-gray-100"
            :title="store.expandedGroups.size > 0 ? '全部折叠' : '全部展开'"
          >
            {{ store.expandedGroups.size > 0 ? '折叠' : '展开' }}
          </button>
        </div>

        <!-- 过滤 -->
        <div class="grid grid-cols-4 gap-1.5">
          <input
            v-model="store.filterProvider"
            placeholder="provider"
            class="text-xs border border-gray-300 rounded px-1.5 py-1"
          />
          <input
            v-model="store.filterModel"
            placeholder="model"
            class="text-xs border border-gray-300 rounded px-1.5 py-1"
          />
          <input
            v-model="store.filterConversationId"
            placeholder="conversation_id"
            class="text-xs border border-gray-300 rounded px-1.5 py-1"
          />
          <select
            v-model="store.filterStatus"
            class="text-xs border border-gray-300 rounded px-1.5 py-1 bg-white"
          >
            <option value="">all status</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="stream_interrupted">interrupted</option>
          </select>
        </div>
      </div>

      <!-- 列表 -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="store.isLoading" class="p-4 text-center text-gray-400 text-sm">
          加载中…
        </div>
        <div
          v-else-if="store.items.length === 0"
          class="p-4 text-center text-gray-400 text-sm"
        >
          该日期暂无日志
        </div>
        <!-- 按时间模式: 平铺列表 -->
        <table v-else-if="store.viewMode === 'time'" class="w-full text-xs">
          <thead class="bg-gray-50 sticky top-0">
            <tr class="text-left text-gray-500">
              <th class="px-2 py-1.5 font-medium">#</th>
              <th class="px-2 py-1.5 font-medium">时间</th>
              <th class="px-2 py-1.5 font-medium">provider</th>
              <th class="px-2 py-1.5 font-medium">model</th>
              <th class="px-2 py-1.5 font-medium text-right">ms</th>
              <th class="px-2 py-1.5 font-medium text-center">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(item, idx) in store.items"
              :key="item.call_id"
              @click="selectRow(item)"
              class="border-t border-gray-100 cursor-pointer hover:bg-blue-50"
              :class="{ 'bg-blue-100': store.selectedDetail?.call_id === item.call_id }"
            >
              <td class="px-2 py-1.5 text-gray-400">
                {{ store.offset + idx + 1 }}
              </td>
              <td class="px-2 py-1.5 font-mono text-gray-700">
                {{ fmtTime(item.timestamp) }}
              </td>
              <td class="px-2 py-1.5">
                <span class="px-1.5 py-0.5 bg-gray-100 rounded text-gray-700">
                  {{ item.provider }}
                </span>
              </td>
              <td class="px-2 py-1.5 text-gray-700 truncate max-w-[120px]" :title="item.model">
                {{ item.model }}
              </td>
              <td class="px-2 py-1.5 text-right font-mono" :class="latencyColor(item.latency_ms)">
                {{ item.latency_ms.toFixed(0) }}
              </td>
              <td class="px-2 py-1.5 text-center">
                <span
                  class="inline-block px-1.5 rounded text-xs font-bold"
                  :class="statusColor(item.status)"
                  :title="item.status"
                >
                  {{ statusLabel(item.status) }}
                </span>
                <span v-if="item.has_tool_use" class="ml-1 text-purple-500" title="调用了工具">
                  🔧
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <!-- 按会话模式: 分组折叠 -->
        <div v-else class="p-2 space-y-1.5">
          <div
            v-for="group in store.groupedByConversation"
            :key="group.conversation_id"
            class="border border-gray-200 rounded bg-white"
          >
            <!-- group header -->
            <div
              class="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-gray-50"
              :class="{ 'bg-gray-50': store.expandedGroups.has(group.conversation_id) }"
              @click="store.toggleGroupExpansion(group.conversation_id)"
            >
              <span
                class="text-gray-400 text-xs w-3"
                :class="{ 'rotate-90': store.expandedGroups.has(group.conversation_id) }"
              >
                ▶
              </span>
              <span class="font-mono text-xs font-medium text-gray-800" :title="group.conversation_id">
                {{ group.display_id }}
              </span>
              <span class="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-medium">
                {{ group.call_count }} 次调用
              </span>
              <span v-if="group.has_error" class="px-1.5 py-0.5 bg-red-50 text-red-600 rounded text-xs">
                有错误
              </span>
              <span class="flex-1 text-xs text-gray-500 truncate">
                {{ group.unique_models.join(', ') }}
              </span>
              <span class="text-xs text-gray-500 font-mono">
                {{ fmtTime(group.first_timestamp) }} → {{ fmtTime(group.last_timestamp) }}
              </span>
              <span class="text-xs font-mono" :class="latencyColor(group.total_latency_ms)">
                Σ {{ group.total_latency_ms.toFixed(0) }}ms
              </span>
              <button
                v-if="group.conversation_id !== '(no-conv)'"
                @click.stop="store.filterByConversation(group.conversation_id)"
                class="text-xs px-1.5 py-0.5 text-blue-600 hover:bg-blue-50 rounded"
                title="只看这个会话的调用"
              >
                过滤
              </button>
            </div>
            <!-- 展开的子项 -->
            <div
              v-if="store.expandedGroups.has(group.conversation_id)"
              class="border-t border-gray-100 bg-gray-50/50"
            >
              <table class="w-full text-xs">
                <tbody>
                  <tr
                    v-for="item in group.items"
                    :key="item.call_id"
                    @click="selectRow(item)"
                    class="border-t border-gray-100 cursor-pointer hover:bg-blue-50"
                    :class="{ 'bg-blue-100': store.selectedDetail?.call_id === item.call_id }"
                  >
                    <td class="px-2 py-1 font-mono text-gray-700 w-20">
                      {{ fmtTime(item.timestamp) }}
                    </td>
                    <td class="px-2 py-1 w-20">
                      <span class="px-1 bg-gray-100 rounded text-gray-600">{{ item.provider }}</span>
                    </td>
                    <td class="px-2 py-1 text-gray-700 truncate max-w-[100px]" :title="item.model">
                      {{ item.model }}
                    </td>
                    <td class="px-2 py-1 text-right font-mono w-16" :class="latencyColor(item.latency_ms)">
                      {{ item.latency_ms.toFixed(0) }}ms
                    </td>
                    <td class="px-2 py-1 text-center w-12">
                      <span
                        class="inline-block px-1 rounded text-xs font-bold"
                        :class="statusColor(item.status)"
                        :title="item.status"
                      >
                        {{ statusLabel(item.status) }}
                      </span>
                      <span v-if="item.has_tool_use" class="ml-0.5 text-purple-500" title="调用了工具">
                        🔧
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="border-t border-gray-200 p-2 flex items-center justify-between text-xs bg-gray-50">
        <span class="text-gray-500">
          {{ store.offset + 1 }}-{{ Math.min(store.offset + store.limit, store.total) }}
          / {{ store.total }}
        </span>
        <div class="flex gap-1">
          <button
            @click="store.prevPage()"
            :disabled="!store.hasPrevPage"
            class="px-2 py-0.5 bg-white border border-gray-300 rounded disabled:opacity-30"
          >
            ←
          </button>
          <button
            @click="store.nextPage()"
            :disabled="!store.hasNextPage"
            class="px-2 py-0.5 bg-white border border-gray-300 rounded disabled:opacity-30"
          >
            →
          </button>
        </div>
      </div>
    </div>

    <!-- 右侧: 详情 -->
    <div class="w-1/2 flex flex-col bg-white">
      <div v-if="store.detailLoading" class="flex-1 flex items-center justify-center text-gray-400">
        加载详情…
      </div>
      <div
        v-else-if="store.detailError"
        class="flex-1 flex items-center justify-center text-red-500 text-sm p-4"
      >
        {{ store.detailError }}
      </div>
      <div
        v-else-if="!store.selectedDetail"
        class="flex-1 flex items-center justify-center text-gray-400 text-sm"
      >
        ← 选左侧一行查看详情
      </div>
      <template v-else>
        <!-- 详情头部 -->
        <div class="p-3 border-b border-gray-200">
          <div class="flex items-center justify-between mb-1.5">
            <div class="flex items-center gap-2">
              <span class="font-mono text-xs text-gray-500">{{ store.selectedDetail.call_id }}</span>
              <button
                @click="store.closeDetail()"
                class="text-gray-400 hover:text-gray-700 text-lg leading-none"
                title="关闭"
              >
                ✕
              </button>
            </div>
            <span
              class="px-2 py-0.5 rounded text-xs font-bold"
              :class="statusColor(store.selectedDetail.status)"
            >
              {{ store.selectedDetail.status }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span class="text-gray-500">开始:</span>
              <span class="ml-1 font-mono">{{ fmtDate(store.selectedDetail.timestamp) }}</span>
            </div>
            <div>
              <span class="text-gray-500">耗时:</span>
              <span
                class="ml-1 font-mono font-bold"
                :class="latencyColor(store.selectedDetail.latency_ms)"
              >
                {{ store.selectedDetail.latency_ms.toFixed(0) }} ms
              </span>
            </div>
            <div>
              <span class="text-gray-500">provider:</span>
              <span class="ml-1 font-mono">{{ store.selectedDetail.provider }}</span>
              <span class="ml-1 text-gray-400">({{ store.selectedDetail.provider_protocol }})</span>
            </div>
            <div>
              <span class="text-gray-500">model:</span>
              <span class="ml-1 font-mono">{{ store.selectedDetail.model }}</span>
            </div>
            <div v-if="store.selectedDetail.conversation_id" class="col-span-2">
              <span class="text-gray-500">conv:</span>
              <span class="ml-1 font-mono">{{ store.selectedDetail.conversation_id }}</span>
            </div>
            <div v-if="store.selectedDetail.error" class="col-span-2">
              <span class="text-gray-500">error:</span>
              <span class="ml-1 text-red-600">{{ store.selectedDetail.error }}</span>
            </div>
          </div>
        </div>

        <!-- tab 切换 -->
        <div class="border-b border-gray-200 flex">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            @click="activeTab = tab.key"
            class="px-3 py-2 text-xs font-medium border-b-2 transition-colors"
            :class="
              activeTab === tab.key
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            "
          >
            <span class="mr-1">{{ tab.icon }}</span>
            {{ tab.label }}
          </button>
        </div>

        <!-- tab 内容 -->
        <div class="flex-1 overflow-y-auto p-3">
          <pre
            v-if="activeTab !== 'messages'"
            class="text-xs font-mono whitespace-pre-wrap break-words text-gray-800 leading-relaxed"
          >{{ detailTabContent }}</pre>
          <div v-else class="space-y-2">
            <div
              v-for="(msg, idx) in detailMessages"
              :key="idx"
              class="border border-gray-200 rounded p-2 bg-gray-50"
            >
              <div class="flex items-center gap-2 mb-1.5">
                <span
                  class="px-1.5 py-0.5 rounded text-xs font-bold"
                  :class="
                    msg.role === 'user'
                      ? 'bg-blue-100 text-blue-700'
                      : msg.role === 'assistant'
                      ? 'bg-green-100 text-green-700'
                      : msg.role === 'system'
                      ? 'bg-purple-100 text-purple-700'
                      : 'bg-gray-200 text-gray-700'
                  "
                >
                  {{ msg.role }}
                </span>
                <span class="text-xs text-gray-400">#{{ idx }}</span>
              </div>
              <pre class="text-xs font-mono whitespace-pre-wrap break-words text-gray-700">{{ formatJSON(msg.content || msg) }}</pre>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 清空确认弹窗 -->
    <div
      v-if="showClearConfirm"
      class="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
      @click.self="showClearConfirm = false"
    >
      <div class="bg-white rounded-lg p-4 shadow-lg max-w-sm">
        <h3 class="font-bold text-sm mb-2">确认清空</h3>
        <p class="text-xs text-gray-600 mb-3">
          将永久删除
          <span v-if="store.selectedDate" class="font-mono">{{ store.selectedDate }}</span>
          <span v-else>所有日期</span>
          的全部 LLM 调用日志,不可恢复。
        </p>
        <div class="flex justify-end gap-2">
          <button
            @click="showClearConfirm = false"
            class="text-xs px-3 py-1 bg-gray-100 rounded"
          >
            取消
          </button>
          <button
            @click="confirmClear"
            class="text-xs px-3 py-1 bg-red-500 text-white rounded"
          >
            清空
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
