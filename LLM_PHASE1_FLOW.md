# LLM 第一阶段响应 — 完整流程分析

> 分析日期: 2026-06-01

## 概览时序

```
用户回车
  │
  ▼
ChatWindow.handleSend()                     ── 前端
  │
  ▼
useApi.chatStream()                         ── SSE ReadableStream 解析
  │  POST /api/chat/stream
  ▼
chat.py::chat_stream()                      ── FastAPI 路由层
  │  yield {"type": "status", "content": "thinking"}
  │
  ▼
ChatEngine.stream_chat_with_messages()      ── 核心引擎
  │
  ├─ 1. 加载/创建 Conversation
  ├─ 2. 添加用户消息
  ├─ 3. 加载 Prompt 设置 (_load_prompt_settings)
  ├─ 4. 构建 messages 数组
  │
  ├─ 5. ⭐ 第一阶段：非流式 LLM 调用 ← 关键瓶颈
  │      response = await self.router.chat(messages, stream=False)
  │
  ├─ 6. 检测 tool_use blocks → 有工具则执行 → 再次调 LLM (循环,最多5次)
  │
  ├─ 7. 保存对话到 DB
  ├─ 8. 流式返回 thinking (SSE)
  ├─ 9. 流式返回 final_response (SSE)
  │
  ▼
AIRouter.chat()                             ── 路由层
  │  _chain() 解析 provider 链
  │
  ▼
OllamaAdapter.chat()                        ── 协议适配层
  │  POST /v1/messages (stream=False)
  │  payload: {model, messages, tools, max_tokens, temperature}
  │
  ▼
Ollama 本地推理                              ── 外部 LLM 服务
    返回: {content: [{type:"text", text:...},
                     {type:"thinking", thinking:...},
                     {type:"tool_use", name:..., input:...}]}
```

---

## 各层详细分析

### 第 1 层 — 前端触发 (`ChatWindow.vue:44-61`)

```typescript
async function handleSend() {
  inputValue.value = ''                           // 清空输入框
  chatStore.addMessage('user', text)              // 立即添加用户气泡
  isLoading.value = true
  thinkingStatus.value = 'thinking'               // 显示"贾维斯正在思考..."
  currentResponse.value = ''
  currentThinking.value = ''
  abortController = new AbortController()

  // ✅ 立刻创建空的 assistant 消息，后续流式填充
  chatStore.addMessage('assistant', '')           // msgIndex = 最后一条
  const msgIndex = chatStore.messages.length - 1
  // ...
  await api.chatStream(request, onToken, onDone, onStatus, onThinking, signal)
}
```

关键点：
- 用户消息**立即**渲染到 UI（非阻塞）
- 空的 assistant 气泡**立即**渲染，后续 token 回填
- `thinkingStatus = 'thinking'` 驱动 loading 动画

### 第 2 层 — SSE 客户端 (`useApi.ts:38-110`)

```typescript
async function chatStream(request, onToken, onDone, onStatus, onThinking, signal) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    body: JSON.stringify(request),
    signal                    // ← AbortSignal 支持取消
  })
  const reader = res.body.getReader()
  // 循环解析 SSE 行: "data: {...}\n"
  // 根据 type 字段路由到不同回调:
  //   token → onToken(content)
  //   thinking → onThinking(content)
  //   thinking_start → onThinking('')
  //   tool_call → onStatus(`tool_call:${tool}:${action}`)
  //   tool_result → onStatus(`tool_result:${tool}:${action}:${status}`)
  //   done → onDone()
}
```

关键点：**在收到第一个 SSE 事件之前，前端一直等待**。整个第一阶段非流式调用期间，前端看不到任何数据。

### 第 3 层 — FastAPI 路由 (`chat.py:65-156`)

```python
async def event_generator():
    # ⚡ 第一步：立即发送 thinking 状态（不等 LLM）
    yield {"event": "status", "data": json.dumps({"type": "status", "content": "thinking"})}

    # 🐢 第二步：调用 chat_engine（阻塞等待第一阶段完成）
    async for content in mediator.chat_engine.stream_chat_with_messages(
        request.message, request.messages, request.model,
        request.conversation_id, request.user_id
    ):
        # content 可能是:
        #   普通文本 → event:"token"
        #   JSON 事件 {type:"tool_call"/"tool_result"/"thinking"...} → event:"tool"/"token"
        ...
```

关键点：
- `yield {"type": "status", "content": "thinking"}` 是**唯一**在第一阶段之前发出的 SSE 事件
- 后续所有数据都阻塞在 `stream_chat_with_messages` 的 async generator 上

### 第 4 层 — ChatEngine 第一阶段 (`chat_engine.py:582-586`) ⭐ 核心

```python
# 5. 第一阶段：非流式调用以检测工具
response = await self.router.chat(messages, model=model, stream=False)
#                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                    关键: stream=False — 完整等待 LLM 返回全部内容
response_text = response.content
```

这是**整个流程的性能瓶颈**。`stream=False` 意味着：
- 必须等 Ollama 生成完所有 tokens（包括 thinking + text + tool_use）
- 用户在这段时间内只能看到 "贾维斯正在思考..."
- thinking（chain-of-thought）通常在 200-2000 tokens，但也要等全部生成完

**response 对象包含三个关键字段** (由 OllamaAdapter 解析):

| 字段 | 来源 | 用途 |
|------|------|------|
| `response.content` | `content_blocks` 中 `type:"text"` 的文本 | 最终回答文字 |
| `response.thinking` | `content_blocks` 中 `type:"thinking"` 的文本 | 推理过程 |
| `response.content_blocks` | 原始 `data["content"]` 数组 | 检测 `tool_use` + 提取工具参数 |

### 第 5 层 — AI Router (`router.py:44-65`)

```python
async def chat(self, messages, model=None, ...):
    model_id = model or self.config.default_model   # 默认 qwen3:4b
    providers = self._chain(model_id, ...)          # ['ollama']

    for prov in providers:
        client = self._get_client(prov, model_id)   # 从缓存获取/创建 OllamaAdapter
        resp = await client.chat(messages, **kwargs)
        #     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #     直接调用适配器，stream=False 透传
        resp.metrics = ResponseMetrics(latency_ms=...)
        return resp
```

路由层几乎无开销。只是做 provider 解析和客户端缓存。

### 第 6 层 — Ollama 适配器 (`ollama.py:64-126`)

```python
async def chat(self, messages, stream=True, ...):
    # stream 被 chat_engine 强制覆盖为 False
    payload = {
        "model": self.model,
        "messages": messages,
        "max_tokens": max_tokens or 4096,
        "temperature": temperature,
        "stream": False,               # ← 非流式
    }
    # 注入工具列表
    tools = tool_registry.build_anthropic_tools()  # 所有注册工具的 JSON Schema
    if tools:
        payload["tools"] = tools

    response = await self.client.post("/v1/messages", json=payload)
    #          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #          阻塞等待 Ollama 完成全部推理

    data = response.json()

    # 解析 content_blocks:
    #   {type: "thinking", thinking: "..."}  → AIResponse.thinking
    #   {type: "text", text: "..."}           → AIResponse.content
    #   {type: "tool_use", name: "...", input: {...}} → AIResponse.content_blocks

    return AIResponse(
        content=content,          # 文本回答（如有工具调用则可能为空）
        thinking=thinking,        # chain-of-thought
        content_blocks=content_blocks,  # 原始 blocks（包含 tool_use）
        ...
    )
```

### 第 7 层 — Ollama 本地推理

Ollama 的 `/v1/messages` 端点（Anthropic 兼容格式），对于 `stream=False`，响应结构：

```json
{
  "id": "msg_xxx",
  "model": "qwen3:4b",
  "content": [
    {"type": "thinking", "thinking": "我需要先理解用户的问题..."},
    {"type": "text", "text": "根据你的问题..."},
    {"type": "tool_use", "name": "file", "id": "toolu_xxx", "input": {"action": "read", "path": "..."}}
  ],
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 1234, "output_tokens": 567}
}
```

流式 (`stream=True`) 的 SSE 事件类型：

| 事件类型 | 说明 |
|---------|------|
| `message_start` | 消息开始，包含 model、usage 信息 |
| `content_block_start` | 内容块开始，`content_block.type` 区分: `text`/`thinking`/`tool_use` |
| `content_block_delta` | 内容增量，`delta.text`、`delta.thinking`、`delta.partial_json` (tool_use 参数) |
| `content_block_stop` | 内容块结束 |
| `message_delta` | 消息级别增量，包含 `stop_reason` |
| `message_stop` | 消息结束 |

---

## 工具调用分支

如果第一阶段响应包含 `tool_use` blocks（`chat_engine.py:592-685`）：

```
第一阶段响应
  │
  ├─ 无 tool_use → 跳到第 7 步（图片路径解析）
  │
  └─ 有 tool_use:
       │
       ├─ yield {"type": "status", "content": "tool_iter_1"}
       │
       ├─ 解析工具调用 (ToolCallParser 或 _extract_tool_calls_from_blocks)
       │
       ├─ yield {"type": "tool_call", "tool":..., "action":..., "params":...}
       │
       ├─ task_executor.execute_step(step)    ← 实际执行工具
       │
       ├─ yield {"type": "tool_result", "tool":..., "status":...}
       │
       ├─ 再次调用 LLM (stream=False) ← 又一次阻塞等待
       │
       └─ 循环检查是否还有 tool_use (最多 MAX_TOOL_ITERATIONS=5 次)
```

---

## 性能特征总结

| 阶段 | 阻塞性质 | 用户感知 |
|------|---------|---------|
| 前端 → 后端 POST | ~1ms | 无感知 |
| 后端立即 yield "thinking" | 0ms | 看到"正在思考..." |
| **第一阶段 LLM 调用** | **2-30 秒** (取决于 prompt 长度和模型) | **等待中，无增量输出** |
| 工具执行 (如有) | 0.1-5 秒/轮 | 看到工具状态卡片 |
| 后续 LLM 调用 (如有) | 2-10 秒/轮 | 等待中 |
| 图片路径解析 | <10ms | 无感知 |
| thinking 流式输出 | 渐进 | 看到"思考过程"逐字展开 |
| 文本流式输出 | 渐进 (8 字符/块) | 看到回答逐字出现 |

**核心瓶颈**: 第一阶段 `stream=False` 导致**首字节时间 (TTFB) = 完整 LLM 推理时间**，用户在此期间只能看到静态的 "贾维斯正在思考..." 动画。

**优化方向**: 将第一阶段也改为流式调用，实时解析 `content_block_start` / `content_block_delta` SSE 事件，边接收边判断是否有 `tool_use` block，如果没有工具调用则直接流式输出给前端。

---

## 优化方案

### 核心思路

利用 Ollama `/v1/messages` 流式 SSE 的 `content_block_start` 事件**提前知道 block 类型**的特性：

- `text` 块 → 流式输出给前端（消除 TTFB 延迟）
- `thinking` 块 → 流式输出给前端（思考过程实时可见）
- `tool_use` 块 → 收集参数，等流式完成后执行工具

### 改动范围

1. **`OllamaAdapter.chat_stream_full()`** — 新方法，从 `/v1/messages` 流式读取，yield 结构化事件
2. **`AIRouter.chat_stream_full()`** — 路由层透传
3. **`ChatEngine.stream_chat_with_messages()`** — 第一阶段改用流式调用，实时 yield 文本/思考，检测到 tool_use 后延迟执行
4. **API 层** — 无需改动（已有的 SSE 事件路由兼容）
