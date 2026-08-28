import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  LLMCallLogSummary,
  LLMCallLogDetail,
  LLMCallLogStats,
} from '@/types'
import { useApi } from '@/composables/useApi'

export const useLLMCallLogsStore = defineStore('llmCallLogs', () => {
  const api = useApi()

  // ── 状态 ───────────────────────────────────────────────────────
  const dates = ref<string[]>([])
  const selectedDate = ref<string | null>(null)  // null = 今天
  const items = ref<LLMCallLogSummary[]>([])
  const total = ref(0)
  const offset = ref(0)
  const limit = ref(50)
  const stats = ref<LLMCallLogStats | null>(null)

  // 当前查看的详情
  const selectedDetail = ref<LLMCallLogDetail | null>(null)
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)

  // 过滤
  const filterConversationId = ref<string>('')
  const filterProvider = ref<string>('')
  const filterModel = ref<string>('')
  const filterStatus = ref<string>('')

  // 视图模式: 按时间 / 按会话分组
  const viewMode = ref<'time' | 'conversation'>('time')
  // 按会话分组后,记录哪些 group 是展开的
  const expandedGroups = ref<Set<string>>(new Set())

  const isLoading = ref(false)
  const errorMessage = ref<string | null>(null)

  // ── 列表 ───────────────────────────────────────────────────────

  async function loadDates() {
    try {
      const r = await api.listLLMCallDates()
      dates.value = r.dates
      // 默认选中最新日期
      if (!selectedDate.value && dates.value.length > 0) {
        selectedDate.value = dates.value[0]
      }
    } catch (e) {
      errorMessage.value = String(e)
    }
  }

  async function loadList() {
    if (isLoading.value) return
    isLoading.value = true
    errorMessage.value = null
    try {
      const r = await api.listLLMCallLogs({
        date: selectedDate.value || undefined,
        limit: limit.value,
        offset: offset.value,
        conversation_id: filterConversationId.value || undefined,
        provider: filterProvider.value || undefined,
        model: filterModel.value || undefined,
        status: filterStatus.value || undefined,
      })
      items.value = r.items
      total.value = r.total
    } catch (e) {
      errorMessage.value = String(e)
      items.value = []
      total.value = 0
    } finally {
      isLoading.value = false
    }
  }

  async function loadStats() {
    try {
      stats.value = await api.getLLMCallStats(selectedDate.value || undefined)
    } catch (e) {
      console.warn('[LLMCallLogs] stats failed:', e)
      stats.value = null
    }
  }

  async function loadDetail(callId: string) {
    detailLoading.value = true
    detailError.value = null
    try {
      selectedDetail.value = await api.getLLMCallLog(callId)
    } catch (e) {
      detailError.value = String(e)
      selectedDetail.value = null
    } finally {
      detailLoading.value = false
    }
  }

  function closeDetail() {
    selectedDetail.value = null
    detailError.value = null
  }

  async function clearLogs(dateOnly?: string) {
    const target = dateOnly ?? selectedDate.value ?? undefined
    try {
      const r = await api.clearLLMCallLogs(target)
      errorMessage.value = null
      // 刷新列表 + 日期
      await Promise.all([loadDates(), loadList(), loadStats()])
      return r
    } catch (e) {
      errorMessage.value = String(e)
      return null
    }
  }

  // ── 过滤重置 ───────────────────────────────────────────────────

  function setDate(date: string | null) {
    selectedDate.value = date
    offset.value = 0
  }

  function resetFilters() {
    filterConversationId.value = ''
    filterProvider.value = ''
    filterModel.value = ''
    filterStatus.value = ''
    offset.value = 0
  }

  function nextPage() {
    if (offset.value + limit.value < total.value) {
      offset.value += limit.value
      loadList()
    }
  }

  function prevPage() {
    if (offset.value > 0) {
      offset.value = Math.max(0, offset.value - limit.value)
      loadList()
    }
  }

  // ── Computed ───────────────────────────────────────────────────

  const hasNextPage = computed(() => offset.value + limit.value < total.value)
  const hasPrevPage = computed(() => offset.value > 0)

  // 当前选中项在列表中的索引 (高亮)
  const selectedIndex = computed(() => {
    if (!selectedDetail.value) return -1
    return items.value.findIndex(it => it.call_id === selectedDetail.value!.call_id)
  })

  // 按会话分组 — 每次 items 变化时重算
  // 返回 [{conversation_id, items: [...], call_count, total_latency, first_ts, last_ts}]
  interface ConversationGroup {
    conversation_id: string  // "(no-conv)" 表示无 conversation_id 的调用
    display_id: string       // 展示用: 短 hash 或 "(无会话 ID)"
    items: LLMCallLogSummary[]
    call_count: number
    total_latency_ms: number
    first_timestamp: string
    last_timestamp: string
    has_error: boolean
    unique_models: string[]
  }

  const groupedByConversation = computed<ConversationGroup[]>(() => {
    const map = new Map<string, LLMCallLogSummary[]>()
    for (const it of items.value) {
      const key = it.conversation_id || '(no-conv)'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(it)
    }
    // 排序: 最近的会话 (按 last_timestamp) 在前
    const groups: ConversationGroup[] = []
    for (const [cid, list] of map.entries()) {
      // list 已经按 timestamp 倒序, 所以 first = list[last_idx], last = list[0]
      const sorted = [...list].sort((a, b) => b.timestamp_ms - a.timestamp_ms)
      const last_ts = sorted[0].timestamp
      const first_ts = sorted[sorted.length - 1].timestamp
      const total_latency = sorted.reduce((sum, it) => sum + it.latency_ms, 0)
      const has_error = sorted.some(it => it.status !== 'success')
      const unique_models = Array.from(new Set(sorted.map(it => it.model)))
      const display = cid === '(no-conv)'
        ? '(无会话 ID)'
        : cid.length > 16 ? cid.slice(0, 8) + '…' + cid.slice(-4) : cid
      groups.push({
        conversation_id: cid,
        display_id: display,
        items: sorted,
        call_count: sorted.length,
        total_latency_ms: total_latency,
        first_timestamp: first_ts,
        last_timestamp: last_ts,
        has_error,
        unique_models,
      })
    }
    // 按最近活动时间倒序
    groups.sort((a, b) =>
      new Date(b.last_timestamp).getTime() - new Date(a.last_timestamp).getTime()
    )
    return groups
  })

  // 切换分组展开
  function toggleGroupExpansion(convId: string) {
    if (expandedGroups.value.has(convId)) {
      expandedGroups.value.delete(convId)
    } else {
      expandedGroups.value.add(convId)
    }
  }

  // 展开所有 / 折叠所有
  function expandAllGroups() {
    expandedGroups.value = new Set(groupedByConversation.value.map(g => g.conversation_id))
  }
  function collapseAllGroups() {
    expandedGroups.value.clear()
  }

  // 按某会话过滤 (从 group 视图跳到时间视图, 并预填 conversation_id)
  function filterByConversation(convId: string) {
    if (convId === '(no-conv)') {
      filterConversationId.value = ''
    } else {
      filterConversationId.value = convId
    }
    viewMode.value = 'time'
    offset.value = 0
    loadList()
  }

  return {
    // 状态
    dates,
    selectedDate,
    items,
    total,
    offset,
    limit,
    stats,
    selectedDetail,
    detailLoading,
    detailError,
    filterConversationId,
    filterProvider,
    filterModel,
    filterStatus,
    isLoading,
    errorMessage,
    viewMode,
    expandedGroups,
    // computed
    hasNextPage,
    hasPrevPage,
    selectedIndex,
    groupedByConversation,
    // actions
    loadDates,
    loadList,
    loadStats,
    loadDetail,
    closeDetail,
    clearLogs,
    setDate,
    resetFilters,
    nextPage,
    prevPage,
    toggleGroupExpansion,
    expandAllGroups,
    collapseAllGroups,
    filterByConversation,
  }
})
