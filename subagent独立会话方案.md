# Subagent 独立会话方案

> 最后更新：2026-07-02
> 状态：设计方案（待实施）
> 适用版本：JARVIS v2 → v3

---

## 🎯 设计动机

### 当前问题

当前 subagent 的展示方式（参见 `前后端展示说明.md`）：

- subagent 的调用/结果作为**普通工具消息**塞在主对话流里
- 整坨 JSON / 折叠卡片都在主对话气泡中
- 看不出"这是一个独立的子会话"
- 想看 subagent 完整思考过程需要展开所有 details
- 子代理之间的中间产物（多次 LLM 调用、tool calls）被压扁

### 用户期望

> **每个 subagent 任务应该有自己独立的会话视图，主会话只关心结果和相关产物；支持从主会话跳转到子会话。**

等价于：**Subagent 从"工具调用"提升为"一等公民会话"。**

---

## 🎨 UX 流程

### 主会话视角（默认）

主对话流里，每个 subagent 调用渲染为一张**紧凑卡片**：

```
┌──────────────────────────────────────────────────────────┐
│ 👤 用户: 调研 3 个数据库对比                              │
├──────────────────────────────────────────────────────────┤
│ 🤖 JARVIS: 我来用 map_reduce 调研 3 个数据库              │
│                                                          │
│ ┌─ Subagent 会话 ──────────────────────────────────┐    │
│ │ 🔬 researcher · map_reduce · 3 子代理 · ⏱ 9.2s    │    │
│ │   任务: 调研 PostgreSQL/MySQL/MongoDB 选型         │    │
│ │   结果: 三者对比选型报告                          │    │
│ │   [查看完整会话 →]                                │    │
│ └─────────────────────────────────────────────────┘    │
│                                                          │
│   综合三份调研, 推荐 PostgreSQL + pgvector, 理由是...     │
└──────────────────────────────────────────────────────────┘
```

**关键**：卡片只占主对话一行或两行，不污染上下文。

### 子会话视角（点击后）

从主会话点击 `[查看完整会话 →]` 打开**右侧抽屉**（Drawer），主对话保持不变：

```
┌──────────────────────────────────┬─────────────────────────────────┐
│                                  │ 🔬 researcher · map_reduce  ✕  │
│ 主对话 (保持显示)                 │ ─────────────────────────────── │
│                                  │ 父会话: 调研数据库选型           │
│ ...                              │ 任务: 调研 PostgreSQL/MySQL/MongoDB│
│                                  │ 触发: map_reduce · 3 子代理      │
│ ┌─ Subagent ─┐                   │                                 │
│ │ researcher │ ← 当前查看        │ ─── 子代理 1: PostgreSQL ───    │
│ │ ...        │                   │ 💭 thinking: 用户在做 RAG...     │
│ │ [查看 →]   │                   │ 📤 [user] 调研 PostgreSQL        │
│ └────────────┘                   │ 💭 thinking: 应该查向量索引...   │
│                                  │ 📥 [assistant] ## PostgreSQL...  │
│ ...                              │ 🔧 tool: web_search("pgvector") │
│                                  │ 📥 [result] pgvector HNSW...     │
│                                  │ ⏱ 8.2s · 412 tokens             │
│                                  │                                 │
│                                  │ ─── 子代理 2: MySQL ───         │
│                                  │ ...                             │
│                                  │                                 │
│                                  │ ─── 综合输出 ───                │
│                                  │ ## 三者对比选型报告              │
│                                  │ PostgreSQL + pgvector 在...     │
│                                  │                                 │
│                                  │ [← 返回主会话]   [↗ 新窗口打开] │
└──────────────────────────────────┴─────────────────────────────────┘
```

### 批量 subagent 时（map_reduce）

子会话视图内**嵌套 3 个子-子会话**（每个 subagent 也是独立会话）。但这样会嵌套太深 → **扁平化**：3 个子代理作为 3 个可切换 tab：

```
┌─────────────────────────────────────────────────────────────┐
│ 🔬 researcher · map_reduce · 3 子代理 · 总 9.2s         ✕  │
├─────────────────────────────────────────────────────────────┤
│ [PostgreSQL ✓ 8.2s] [MySQL ✓ 9.1s] [MongoDB ✓ 7.8s] [+综合] │
├─────────────────────────────────────────────────────────────┤
│ 💭 thinking: 用户关心的是 RAG 场景, pgvector 是关键...      │
│ 📤 [user] 调研 PostgreSQL 在 RAG 场景下的表现              │
│ 💭 thinking: 2026 年主流版本 pgvector 0.7+, 支持 HNSW...  │
│ 📥 [assistant] ## PostgreSQL 调研...                       │
│ 🔧 tool_call: web_search("pgvector HNSW 性能 2026")       │
│ 📥 tool_result: ...                                        │
│ ⏱ 8.2s · 412 tokens · success                             │
└─────────────────────────────────────────────────────────────┘
```

每个 tab 展示对应子代理的**完整执行轨迹**。

---

## 🏗 数据模型改动

### Conversation 实体扩展

```python
# jarvis/core/entities.py — Conversation 加 4 个字段
@dataclass
class Conversation:
    conversation_id: str
    user_id: str = ""
    topic: Optional[str] = None
    messages: list[Message] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # ── 新增字段 ──
    parent_conversation_id: Optional[str] = None  # 父会话 (None = 主会话)
    session_kind: str = "main"                      # "main" | "subagent"
    subagent_role: Optional[str] = None            # researcher / coder / ...
    subagent_task: Optional[str] = None             # 触发时的任务描述
    triggered_by_message_id: Optional[str] = None  # 主会话里哪条消息触发的
    metadata: dict = field(default_factory=dict)    # 自由扩展 (mode, batch_size, ...)
```

### DB Schema 迁移

```sql
-- conversations 表加列 (兼容已存在 DB)
ALTER TABLE conversations ADD COLUMN parent_conversation_id TEXT;
ALTER TABLE conversations ADD COLUMN session_kind TEXT DEFAULT 'main';
ALTER TABLE conversations ADD COLUMN subagent_role TEXT;
ALTER TABLE conversations ADD COLUMN subagent_task TEXT;
ALTER TABLE conversations ADD COLUMN triggered_by_message_id TEXT;
ALTER TABLE conversations ADD COLUMN metadata TEXT;  -- JSON

CREATE INDEX IF NOT EXISTS idx_parent ON conversations(parent_conversation_id);
CREATE INDEX IF NOT EXISTS idx_kind ON conversations(session_kind);
```

### 为什么 subagent 用独立 Conversation 而不是 ToolMessage？

| 维度 | 当前 (ToolMessage) | 改进 (独立 Conversation) |
|---|---|---|
| 中间 LLM 调用 | 看不到 | 全部记录 |
| thinking 过程 | 丢失 | 持久化 |
| 工具调用细节 | 折叠在 JSON 里 | 独立消息 |
| 可重放 | 不可 | 可重新加载完整会话 |
| 可跳转 | 无 | 链接即会话 |
| 可分享 | 无 | 有 conversation_id 即可分享 |
| DB 行数 | 不增加 | 每次 subagent 1 行 |
| 写入开销 | 低 | 中（要持久化每条消息） |

---

## 🔌 后端 API 改动

### 新增端点

```python
# jarvis/api/memory.py 新增 3 个端点

@app.get("/api/memory/conversation/{conv_id}/sub_sessions")
async def list_sub_sessions(conv_id: str) -> list[dict]:
    """列出某主会话下的所有 subagent 子会话."""
    return await memory_store.list_sub_sessions(parent_id=conv_id)

@app.get("/api/memory/sub_session/{sub_id}")
async def get_sub_session(sub_id: str) -> dict:
    """获取单个子会话完整内容."""
    return await memory_store.get_conversation(sub_id)

@app.get("/api/memory/conversation/{conv_id}/sub_session_summary")
async def get_sub_session_summaries(conv_id: str) -> list[dict]:
    """获取所有子会话的摘要 (用于主会话卡片快速显示)."""
    return await memory_store.list_sub_sessions(parent_id=conv_id, summary_only=True)
```

### MemoryStore 新增方法

```python
# jarvis/core/memory_store.py
class SQLiteMemoryRepository:
    async def list_sub_sessions(
        self,
        parent_id: str,
        summary_only: bool = False,
    ) -> list[dict]:
        """按 parent_conversation_id 查询子会话."""
        # SELECT conversation_id, subagent_role, subagent_task, 
        #        session_kind, metadata, created_at, updated_at
        #   FROM conversations
        #  WHERE parent_conversation_id = ?
        #  ORDER BY created_at DESC
    
    async def save_sub_session(self, conv: Conversation) -> bool:
        """保存 subagent 子会话 (复用 save_conversation 但 parent_id 已设)."""
        return await self.save_conversation(
            conv.conversation_id, conv.user_id,
            [m.to_dict() for m in conv.messages],
            conv.context,
            topic=conv.topic,
        )
```

---

## 🔧 后端逻辑改动

### SubagentOrchestrator 改造

```python
# jarvis/core/subagent.py — 改动 BaseSubagent.run()
class BaseSubagent:
    def __init__(self, router, ..., 
                 parent_conversation: Optional[Conversation] = None,
                 message_store: Optional[Any] = None,  # MemoryStore
                 work_folder: Optional[str] = None):
        # ...
        self.parent = parent_conversation
        self.store = message_store
        self.session = self._init_session()  # 子会话
    
    def _init_session(self) -> Conversation:
        """创建/加载 subagent 子会话."""
        if self.parent is None:
            return None  # 不需要持久化 (单元测试场景)
        return Conversation(
            conversation_id=str(uuid.uuid4()),
            user_id=self.parent.user_id,
            topic=f"[{self.role.value}] {self.task[:40]}",
            parent_conversation_id=self.parent.conversation_id,
            session_kind="subagent",
            subagent_role=self.role.value,
            subagent_task=self.task,
        )
    
    async def run(self, task, context=None) -> SubagentResult:
        session = self.session
        if session is not None:
            self._record_user_message(session, task, context)
        
        resp = await self.router.chat(messages, model=self.config.model, stream=False)
        
        if session is not None:
            self._record_assistant_message(session, resp.content, resp.thinking)
            await self._persist_session(session)
        
        return SubagentResult(
            role=self.role, task=task, success=True,
            output=resp.content,
            sub_session_id=session.conversation_id if session else None,  # 新增
            ...
        )
    
    async def _persist_session(self, session: Conversation):
        if self.store:
            await self.store.save_sub_session(session)
```

### SubagentStrategy 改动

```python
# jarvis/core/task_engine.py — SubagentStrategy.execute 返回值加 sub_session_id

# 单任务模式
{
    "status": "success",
    "role": "researcher",
    "task": "...",
    "output": "...",
    "sub_session_id": "uuid-xxx",   # 新增
    "elapsed_ms": ...,
}

# 批量模式
{
    "status": "success",
    "mode": "map_reduce",
    "results": [
        {
            "role": "researcher",
            "task": "...",
            "output": "...",
            "sub_session_id": "uuid-1",  # 新增
            "success": True,
            "elapsed_ms": ...,
        },
        ...
    ],
    "reduced_output": "...",
    "sub_session_ids": ["uuid-1", "uuid-2", "uuid-3"],  # 新增
}
```

### ChatEngine 接线

```python
# jarvis/core/chat_engine.py — ChatEngine.__init__
from jarvis.core.subagent import SubagentOrchestrator

self.subagent_orchestrator = SubagentOrchestrator(
    router=self.router,
    work_folder=self.work_folder,
    message_store=memory_store,                      # 新增
    parent_conversation_provider=self._get_or_create_current,  # 新增
)
```

---

## 🎨 前端改动

### 新组件

```
frontend/src/components/
├── SubagentCard.vue          # 主会话里的紧凑卡片
├── SubagentSessionPanel.vue  # 右侧抽屉, 完整会话
└── SubagentBatchTabs.vue     # map_reduce 的 tab 切换
```

### SubagentCard.vue（主会话用）

```vue
<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  subagent: {
    role: string
    task: string
    mode: string  // single / sequential / parallel / map_reduce
    output?: string
    results?: SubagentItem[]
    reduced_output?: string
    status: 'success' | 'partial' | 'error'
    elapsed_ms?: number
    sub_session_ids?: string[]  // 新增
  }
}
const props = defineProps<Props>()
const emit = defineEmits<{
  openSession: [subSessionId: string]
  openBatch: [subSessionIds: string[], activeIndex: number]
}>()

const isBatch = computed(() => Array.isArray(props.subagent.results))

const summary = computed(() => {
  if (props.subagent.reduced_output) {
    return props.subagent.reduced_output.slice(0, 200)
  }
  if (props.subagent.output) {
    return props.subagent.output.slice(0, 200)
  }
  return ''
})

const ROLE_META = {
  researcher: { icon: '🔬', color: 'blue', label: 'Researcher' },
  coder: { icon: '💻', color: 'green', label: 'Coder' },
  reviewer: { icon: '🔍', color: 'purple', label: 'Reviewer' },
  summarizer: { icon: '📝', color: 'amber', label: 'Summarizer' },
  planner: { icon: '📐', color: 'cyan', label: 'Planner' },
  general: { icon: '🤖', color: 'gray', label: 'General' },
}

function openMainSession() {
  if (props.subagent.sub_session_ids?.[0]) {
    emit('openSession', props.subagent.sub_session_ids[0])
  }
}
function openBatch() {
  if (props.subagent.sub_session_ids) {
    emit('openBatch', props.subagent.sub_session_ids, 0)
  }
}
</script>

<template>
  <div class="border border-border rounded-xl overflow-hidden bg-card my-2">
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 bg-muted/40 border-b border-border text-xs">
      <span :class="['px-1.5 py-0.5 rounded font-medium',
                     `bg-${ROLE_META[subagent.role]?.color}-100`,
                     `text-${ROLE_META[subagent.role]?.color}-700`]">
        {{ ROLE_META[subagent.role]?.icon }} {{ ROLE_META[subagent.role]?.label }}
      </span>
      <span v-if="subagent.mode !== 'single'" class="text-muted-foreground">
        ⚡ {{ subagent.mode }}
      </span>
      <span v-if="isBatch" class="text-muted-foreground">
        · {{ subagent.results!.length }} 个子代理
      </span>
      <span class="flex-1"></span>
      <span v-if="subagent.elapsed_ms" class="text-muted-foreground">
        ⏱ {{ (subagent.elapsed_ms / 1000).toFixed(1) }}s
      </span>
      <span :class="subagent.status === 'success' ? 'text-green-600' :
                   subagent.status === 'partial' ? 'text-amber-600' : 'text-red-600'">
        {{ subagent.status === 'success' ? '✅' : subagent.status === 'partial' ? '⚠️' : '❌' }}
      </span>
    </div>

    <!-- Body -->
    <div class="px-3 py-2 text-xs">
      <div class="text-muted-foreground mb-1">
        📋 {{ subagent.task.slice(0, 80) }}{{ subagent.task.length > 80 ? '…' : '' }}
      </div>
      <div v-if="summary" class="text-foreground/80 line-clamp-2">
        {{ summary }}{{ summary.length >= 200 ? '…' : '' }}
      </div>
    </div>

    <!-- Action -->
    <div class="px-3 py-1.5 border-t border-border/50 bg-muted/20">
      <button
        v-if="isBatch"
        @click="openBatch"
        class="text-xs text-primary hover:underline"
      >
        查看 {{ subagent.results!.length }} 个子代理会话 →
      </button>
      <button
        v-else
        @click="openMainSession"
        class="text-xs text-primary hover:underline"
      >
        查看完整会话 →
      </button>
    </div>
  </div>
</template>
```

### SubagentSessionPanel.vue（抽屉）

```vue
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  subSessionId: string | null  // null = 关闭
  batchIds?: string[]          // 批量时多个会话
  initialTab?: number
}>()
const emit = defineEmits<{ close: [] }>()

const activeTab = ref(props.initialTab ?? 0)
const session = ref<any>(null)
const loading = ref(false)

watch(() => props.subSessionId, async (id) => {
  if (!id) return
  loading.value = true
  const res = await fetch(`/api/memory/sub_session/${id}`)
  session.value = await res.json()
  loading.value = false
}, { immediate: true })

const isOpen = computed(() => 
  props.subSessionId !== null || (props.batchIds && props.batchIds.length > 0)
)
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <Transition name="fade">
      <div v-if="isOpen" class="fixed inset-0 bg-black/30 z-40"
           @click="emit('close')"></div>
    </Transition>
    
    <!-- Drawer -->
    <Transition name="slide">
      <div v-if="isOpen"
           class="fixed top-0 right-0 bottom-0 w-[600px] max-w-[90vw] bg-background
                  border-l border-border shadow-2xl z-50 flex flex-col">
        <!-- Header -->
        <div class="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span class="text-sm font-medium">
            {{ session?.subagent_role || 'Subagent' }} 会话
          </span>
          <span class="text-xs text-muted-foreground flex-1 truncate">
            {{ session?.subagent_task }}
          </span>
          <button @click="emit('close')" class="text-muted-foreground hover:text-foreground">
            ✕
          </button>
        </div>
        
        <!-- Tabs (batch) -->
        <div v-if="batchIds && batchIds.length > 0"
             class="flex border-b border-border overflow-x-auto">
          <button v-for="(id, i) in batchIds" :key="id"
                  @click="activeTab = i"
                  :class="['px-3 py-2 text-xs whitespace-nowrap',
                           activeTab === i ? 'border-b-2 border-primary text-foreground' :
                                             'text-muted-foreground']">
            子代理 {{ i + 1 }}
          </button>
        </div>
        
        <!-- Body: messages -->
        <div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          <div v-if="loading" class="text-center text-muted-foreground py-8">
            加载中…
          </div>
          <div v-else-if="session" class="space-y-2">
            <div v-for="m in session.messages" :key="m.message_id"
                 :class="['text-sm rounded-lg p-3',
                          m.role === 'user' ? 'bg-primary/10' :
                          m.role === 'assistant' ? 'bg-muted' :
                          'bg-amber-50 border border-amber-200']">
              <div class="text-xs text-muted-foreground mb-1">
                {{ m.role }} · {{ new Date(m.timestamp).toLocaleString() }}
              </div>
              <div v-if="m.thinking" class="text-xs italic text-muted-foreground mb-2">
                💭 {{ m.thinking }}
              </div>
              <div v-html="renderMarkdown(m.content)"></div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
```

### ChatWindow.vue 集成

```vue
<script setup>
// ... 已有代码 ...

const showSubagentPanel = ref(false)
const currentSubSessionId = ref<string | null>(null)
const currentBatchIds = ref<string[]>([])

function openSubagentSession(subSessionId: string) {
  currentSubSessionId.value = subSessionId
  currentBatchIds.value = []
  showSubagentPanel.value = true
}

function openSubagentBatch(subSessionIds: string[], initialTab = 0) {
  currentBatchIds.value = subSessionIds
  currentSubSessionId.value = subSessionIds[initialTab] ?? null
  showSubagentPanel.value = true
}

// 替换原来的 SubagentCall 渲染:
function renderToolMessage(msg: Message) {
  if (msg.role === 'tool' && /* tool === 'subagent' */) {
    return h(SubagentCard, {
      subagent: msg.parsedSubagent,
      onOpenSession: openSubagentSession,
      onOpenBatch: openSubagentBatch,
    })
  }
  // 其他工具走原来的渲染
}
</script>

<template>
  <!-- 已有 chat 内容 -->
  
  <!-- 新增: subagent session 抽屉 -->
  <SubagentSessionPanel
    v-if="showSubagentPanel"
    :sub-session-id="currentSubSessionId"
    :batch-ids="currentBatchIds"
    @close="showSubagentPanel = false"
  />
</template>
```

---

## 📊 完整数据流

```
用户: "调研 PG/MySQL/MongoDB"
                    │
                    ▼
ChatEngine.stream_chat_with_messages
                    │
                    ├─ 主 LLM 输出 tool_use {name: "subagent", params: {...}}
                    │
                    ├─ tool_call SSE → frontend
                    │   {type: "tool_call", tool: "subagent", params: {...}}
                    │
                    ├─ TaskExecutor.execute_step(Step(tool="subagent"))
                    │
                    ├─ SubagentStrategy.execute
                    │   │
                    │   └─ SubagentOrchestrator.run_batch(MAP_REDUCE, requests)
                    │       │
                    │       ├─ 创建 3 个独立 Conversation (parent = main_conv)
                    │       │
                    │       ├─ ResearcherSubagent[1].run()
                    │       │   ├─ 子会话记录 [user]: "调研 PostgreSQL"
                    │       │   ├─ router.chat(...) → 拿到 response
                    │       │   ├─ 子会话记录 [assistant]: "...", thinking: "..."
                    │       │   ├─ 子会话持久化到 DB
                    │       │   └─ 返回 SubagentResult(sub_session_id=uuid1, ...)
                    │       │
                    │       ├─ ResearcherSubagent[2].run() → uuid2
                    │       ├─ ResearcherSubagent[3].run() → uuid3
                    │       │
                    │       └─ reduce_prompt → 综合输出
                    │
                    ├─ tool_result SSE → frontend
                    │   {type: "tool_result", tool: "subagent",
                    │    result: {mode, results[], reduced_output,
                    │             sub_session_ids: [uuid1, uuid2, uuid3]}}
                    │
                    └─ 主对话收到结果, 生成最终回复

前端:
   ChatMessage.vue 检测 tool === 'subagent'
                    │
                    ├─ 渲染 <SubagentCard :subagent="..." />
                    │   ├─ 头部: 角色徽章 + 模式 + 状态 + 耗时
                    │   ├─ 摘要: 任务 + 摘要前 200 字
                    │   └─ 操作: [查看 3 个子代理会话 →]
                    │
                    └─ 用户点击 → <SubagentSessionPanel :batchIds=[u1,u2,u3] />
```

---

## 📋 实施 Roadmap

### Phase 1：基础设施（半天）

| 步骤 | 文件 | 工作量 |
|---|---|---|
| 1.1 扩展 Conversation 实体 + 5 字段 | `jarvis/core/entities.py` | 15 min |
| 1.2 DB Schema 迁移（ALTER TABLE） | `jarvis/core/memory_store.py` `_init_table` | 20 min |
| 1.3 MemoryStore 新增 list_sub_sessions / save_sub_session | `jarvis/core/memory_store.py` | 30 min |
| 1.4 API 新增 3 个端点 | `jarvis/api/memory.py` | 20 min |

### Phase 2：后端逻辑（半天）

| 步骤 | 文件 | 工作量 |
|---|---|---|
| 2.1 BaseSubagent 加 parent_conversation / message_store / session | `jarvis/core/subagent.py` | 45 min |
| 2.2 BaseSubagent.run 加持久化逻辑 | `jarvis/core/subagent.py` | 30 min |
| 2.3 SubagentResult 加 sub_session_id 字段 | `jarvis/core/subagent.py` | 10 min |
| 2.4 SubagentStrategy.execute 把 sub_session_ids 加入返回 | `jarvis/core/task_engine.py` | 15 min |
| 2.5 ChatEngine 注入 message_store + parent provider | `jarvis/core/chat_engine.py` | 15 min |

### Phase 3：前端组件（半天）

| 步骤 | 文件 | 工作量 |
|---|---|---|
| 3.1 新增 SubagentCard.vue | `frontend/src/components/SubagentCard.vue` | 30 min |
| 3.2 新增 SubagentSessionPanel.vue（抽屉） | `frontend/src/components/SubagentSessionPanel.vue` | 60 min |
| 3.3 ChatWindow.vue 集成 + 事件路由 | `frontend/src/components/ChatWindow.vue` | 30 min |
| 3.4 TypeScript 类型扩展 | `frontend/src/types/index.ts` | 10 min |

### Phase 4：测试（半天）

| 步骤 | 文件 | 工作量 |
|---|---|---|
| 4.1 后端：subagent 创建子会话 + 持久化 | `tests/test_subagent.py` | 45 min |
| 4.2 后端：API 端点测试 | `tests/test_api_sub_sessions.py` | 30 min |
| 4.3 前端组件快照测试（可选） | — | — |

**总计：2-3 个工作日可完成完整改造。**

---

## 🚧 风险与缓解

| 风险 | 缓解 |
|---|---|
| DB 行数爆炸 (map_reduce × N) | 加 `archived` 字段, 30 天后可清理; 默认不在 sidebar 显示 |
| 子会话污染 Conversation 列表 | 列表 API 默认过滤 `session_kind='main'` |
| 持久化失败导致 subagent 数据丢失 | 错误时降级为内存 (已有逻辑), 仅记录 warning |
| 嵌套 subagent (subagent 自己调 subagent) | `parent_conversation_id` 可以是多级, 但 UI 暂只展示 1 级 |
| 前端抽屉性能 (子会话 100+ 消息) | 虚拟滚动 (`@tanstack/vue-virtual`) |

---

## 🎁 附赠收益

实施后还白送这些能力：

1. **可分享的 subagent URL** — 直接打开 `/sub-session/uuid` 看完整 trace
2. **subagent 历史审计** — 列出某用户所有 subagent 调用历史
3. **A/B 测试 subagent** — 同任务不同 subagent_role 的结果对比
4. **subagent 调试** — 重放某个 subagent 会话看哪一步出错
5. **Token 成本分析** — 每个 subagent 独立统计 token 用量

---

## 📚 相关文档

- `subagent说明.md` — 当前 subagent 行为
- `前后端展示说明.md` — 当前展示方案
- `CLAUDE.md` — Conversation 实体 + MemoryStore 章节
- `jarvis_architecture_v2.puml` — 当前架构图

---

*设计方案 v1.0*