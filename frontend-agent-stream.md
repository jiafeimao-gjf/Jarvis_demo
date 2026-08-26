# 前端 Stream 请求处理 — 变更计划

## 背景

`frontend/src/composables/useApi.ts::chatStream()` 用 `fetch` + `getReader()` 自己解析 SSE。
Review 后发现 3 个需要修复的问题（P0 一个、P1 两个），外加 2 项可选加固。

## 当前事件矩阵

后端 `jarvis/api/chat.py:80-258` 共发出 **8 种 SSE event**：

| event 名 | data.type | 当前前端处理 | 状态 |
|---|---|---|---|
| `status` | `status` | `onStatus("thinking")` | ✅ |
| `token` | `token` | `onToken(content)` | ✅ |
| `tool` | `tool_call` / `tool_result` / `tool_skipped` | 只识别前两个 | ⚠️ `tool_skipped` 静默丢 |
| `audio` | (binary PCM b64) | `onAudio` | ✅ |
| `tts_fallback` | `tts_fallback` | `onTTSFallback` | ✅ |
| `audio_done` | `audio_done` | `onAudioDone` | ✅ |
| `done` | `done` (含 `full_response` + `conversation_id`) | **被忽略**，仅靠 stream 关闭 fallback | ⚠️ 字段未利用 |
| `error` | `error` | **被静默丢弃** | ❌ |

---

## 修改 1：🔴 P0 — 错误事件丢失

### 问题

`useApi.ts:107-156` 的分发器只处理 6 种 event 名（`audio` / `audio_done` / `tts_fallback` / `token` / `message` / `tool`）。
当 `currentEvent === 'error'` 或 `'done'` 时，整条事件被默默丢弃。

**后果**：后端 stream 中途异常（如 agent loop 抛错、tool 执行失败、`AgentLoopRunner` yield `tool_result` 后下一轮 LLM 报 400），ChatWindow 永远只看到通用 `抱歉，发生错误：xxx`，看不到后端实际的 `str(e)`。
最坏情况：LLM 已经在流，但工具循环因 anthropic 协议不匹配被中断，前端**完全感知不到错误来源**。

### 修复

在 `useApi.ts::chatStream()` 分发表添加两个分支：

```javascript
// useApi.ts ~line 117 (在 audio_done / tts_fallback 之后)
} else if (currentEvent === 'error') {
  // 后端异常 — 透传给 onStatus, 由 ChatWindow 决定怎么展示
  onStatus?.({
    type: 'error',
    content: (data && (data.content || data.message)) || 'Unknown stream error',
  })
} else if (currentEvent === 'done') {
  // 后端权威完整文本 — 用于 reconcile (防 token 丢包) + 同步 conversation_id
  onStatus?.({
    type: 'done',
    content: (data && data.content) || '',
    conversation_id: (data && data.conversation_id) || null,
  })
  onDone?.()                              // 显式触发, 不依赖 stream 关闭 fallback
}
```

`ChatWindow.vue::onStatus` 的 `else` 分支新增：

```javascript
} else if (status.type === 'error') {
  // 流中途错误 — 替换占位 assistant 消息为具体错误, 不要仅显示通用 "抱歉"
  if (chatStore.messages[msgIndex]) {
    chatStore.messages[msgIndex].content =
      `⚠️ 后端错误: ${status.content}`
  }
  isLoading.value = false
  thinkingStatus.value = 'error'
}
```

---

## 修改 2：🟡 P1 — `done` 事件 reconcile

### 问题

后端 `done` 事件的 `content` 字段是**完整文本**（chat engine 的 `final_result.final_text`），
不含累积的 thinking / 工具元数据，是 LLM 真正输出的权威结果。

当前 `useApi.ts:160-161` 只在 `reader.read()` 返回 `done: true` 后才调 `onDone?.()`，
**忽略了 `done` 事件带过来的 `content` 字段**。

**后果**：网络丢包时（中间几个 token 丢失），UI 文本不完整；后端明明知道完整文本却没用。

### 修复

承接修改 1 中的 `done` 分支，新增 `onStatus({ type: 'done', content, conversation_id })`。
`ChatWindow.vue::onStatus` 添加 reconcile 逻辑：

```javascript
} else if (status.type === 'done') {
  // 与本地累积的 token 做 reconcile — 取最长 (防 token 丢包)
  if (typeof status.content === 'string'
      && status.content.length > currentResponse.value.length) {
    currentResponse.value = status.content
    if (chatStore.messages[msgIndex]) {
      chatStore.messages[msgIndex].content = status.content
    }
  }
  // conversation_id 由 useApi 透传后再处理 (后端新建对话场景)
}
```

`conversation_id` 同步需要 `onStatus` 知道 `msgIndex`，所以在 `chatStream()` 签名上**不**新增
第 9 个回调 — 复用现有 `onStatus` 通道（structured payload）。

---

## 修改 3：🟡 P1 — `tool_skipped` UI 反馈

### 问题

PR2 在 `AgentLoopRunner` 里加了 dedup：相同 `(tool, params)` 第二次调用直接跳过，
yield `{"type": "tool_skipped", "tool": ..., "reason": "duplicate"}`。

后端 `chat.py:189-191` 把这条数据归到 `event: tool` SSE 名下发；
前端 `ChatWindow.vue:418-437` 只认 `tool_call` 和 `tool_result`，跳过事件不展示。

**后果**：用户问"帮我读 x.txt + 再读一次 x.txt"，前端只看到一次 `tool_call` + 一次 `tool_result`，
LLM 实际是想调 2 次（虽然只执行 1 次）。用户对 agent 的"我决定不重复"行为没有反馈。

### 修复

`ChatWindow.vue` 引入一个轻量级 toast 状态：

```typescript
// 顶部 <script setup>
const toolCallStatus = ref<string | null>(null)
let toolCallStatusTimer: number | null = null

function flashToolStatus(msg: string) {
  toolCallStatus.value = msg
  if (toolCallStatusTimer) clearTimeout(toolCallStatusTimer)
  toolCallStatusTimer = window.setTimeout(() => {
    toolCallStatus.value = null
  }, 1500)
}
```

`onStatus` 分支新增：

```javascript
} else if (status.type === 'tool_skipped') {
  // PR2 dedup 跳过的重复调用 — 1.5s 灰条提示
  flashToolStatus(`已跳过重复: ${status.tool}`)
}
```

模板内（输入框上方或消息流末尾）渲染：

```html
<div v-if="toolCallStatus"
     class="text-xs text-muted-foreground px-2 py-1 bg-secondary/40 rounded mx-auto my-1">
  ⚙ {{ toolCallStatus }}
</div>
```

---

## 修改 4：🟢 可选 — `topic_update` event 名固化

### 现状

后端 `chat.py:189-191`：
```python
sse_event = "tool" if evt_type.startswith("tool") else "token"
```

`topic_update` 不以 `tool` 开头，被归到 `event: token`。前端 `useApi.ts:123` 在
`token`/`message` 分支里再按 `data.type === 'topic_update'` 二次分发 — **能用但语义错位**。

### 建议（不阻塞）

改 `chat.py:189-191` 用显式映射：
```python
SSE_EVENT_FOR_TYPE = {
    "tool_call": "tool",
    "tool_result": "tool",
    "tool_skipped": "tool",
    "thinking_start": "thinking_event",
    "thinking": "thinking_event",
    "thinking_end": "thinking_event",
    "topic_update": "topic",
}
sse_event = SSE_EVENT_FOR_TYPE.get(evt_type, "token")
```

**风险**：会改 SSE event 名，前端 useApi.ts 分发表也要同步调整。建议放到下一个 PR 一起做，
本 PR 不动以保持最小变更。

---

## 修改 5：🟢 可选 — decoder flush on stream end

### 现状

```javascript
buffer += decoder.decode(value, { stream: true })
```

`stream: true` 让 decoder 保留多字节 UTF-8 跨 chunk 状态。
但 stream 突然中断时，buffer 里的尾部 partial SSE 事件从未被 flush。
`reader.read()` 返回 `done: true` 后也没调 `decoder.decode()` 强制 flush。

**影响**：正常 close 下没问题（服务端发完整 `\n\n` 才结束）；异常断连时丢最后半行。
**建议**：reader 循环退出后加一次：

```javascript
// stream ended — flush decoder, 强制处理残余 buffer
const tail = decoder.decode()
if (tail) buffer += tail
if (buffer.trim()) {
  // 尝试按 \n 拆最后一行 (虽然没有 \n 终止, 仍按 SSE 协议尝试 parse)
  processLine(buffer)
}
buffer = ''
```

风险低，建议与修改 1 一起合并（同一文件）。

---

## 文件清单

### 修改

- `frontend/src/composables/useApi.ts` — `chatStream()` 加 `done` / `error` 分支 (修改 1+2+5)
- `frontend/src/components/ChatWindow.vue` — `onStatus` 加 `error` / `done` / `tool_skipped` 处理 + `toolCallStatus` 模板 (修改 1+2+3)

### 不修改（本 PR 不动）

- `frontend/src/stores/chat.ts` — `addMessage` / `applyTopicUpdate` 已够用
- `jarvis/api/chat.py` — `done` / `error` 事件已正确发出，等前端接住即可
- `jarvis/core/agent_loop.py` — `tool_skipped` 事件已 yield，无需改

### 新增

- `frontend/tests/chatStream.test.ts` (vitest) — 5 个 mock fetch + getReader 的用例
  - `test_done_event_triggers_onDone_with_content` — `done` 触发 onDone + reconcile payload
  - `test_error_event_surfaces_content_to_onStatus` — `error` 透传 data.content
  - `test_tool_skipped_event_emits_status` — `tool_skipped` 走 status channel
  - `test_audio_done_event_triggers_callback` — `audio_done` 仍正常
  - `test_partial_buffer_flush_on_stream_end` — decoder.flush 残留处理

> 注：项目目前**没有 frontend 单测基础设施**（`package.json` 没有 vitest/jest 依赖）。
> 测试可能是更大工作 — 建议先建 `vitest.config.ts` + 装 `vitest` 包，作为单独 PR。
> 本 PR 优先写代码 + 手动验证，测试放下一轮。

---

## 测试策略（手动）

1. **错误事件** — 临时把 `chat.py` 的 `event_generator` 改成 `raise RuntimeError("测试错误")`
   验证 ChatWindow 是否显示 `⚠️ 后端错误: 测试错误`
2. **done reconcile** — 在 token 流中故意丢一两个（修改后端 yield token 时跳一个）
   验证 UI 文本是否最终与后端 `full_response` 一致
3. **tool_skipped** — 问 "读 x.txt 然后再读一次 x.txt"，
   验证第二个 tool_call 是否触发 1.5s "已跳过重复: file" 提示

---

## 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| 改 `onStatus` 的 status.type 分发，可能影响现有 chatStore 状态 | 中 | `tool_skipped` 不改 chatStore 只改本地 UI state；`error` / `done` 只在 stream 末尾触发, 不会和 token 流冲突 |
| 后端 `done.content` 比 UI 长 → 用户看到文本"跳变" | 低 | 流结束后才 reconcile, 用户视觉上感受不到 |
| SSE event 名 "error" 是 SSE 协议保留字（client→server 的 close） | 低 | 这里只作 event name, 不触发协议保留行为；如担心可改名 `stream_error` |

---

## 验收清单

- [ ] useApi.ts `done` 分支正确触发 onDone 并传 `content` / `conversation_id`
- [ ] useApi.ts `error` 分支把 `data.content` 透传给 onStatus
- [ ] ChatWindow.vue 流末尾 reconcile 生效（丢 token 场景）
- [ ] ChatWindow.vue 收到 `tool_skipped` 显示 1.5s 灰条
- [ ] ChatWindow.vue 收到 `error` 把当前 assistant message 替换为错误提示
- [ ] npx vue-tsc --noEmit 通过
- [ ] 全量 backend pytest 仍 275 passed（不涉及 backend 改动）

---

## 排期

| 任务 | 预计 |
|---|---|
| useApi.ts 改 3 个分支 | 30 min |
| ChatWindow.vue 改 onStatus + 新增 toolCallStatus state + 模板 | 45 min |
| 手动测试 3 个场景 | 30 min |
| vue-tsc 校验 | 5 min |
| **合计** | **~2h** |

PR 标题建议：`fix(chat-frontend): 修 SSE error 事件丢失 + done reconcile + tool_skipped UI 反馈`
