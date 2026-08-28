# Agent Loop 核心逻辑 & Stream 接口梳理

> 文档日期：2026-08-28
> 范围：`jarvis/core/agent_loop.py`、`jarvis/core/chat_engine.py`、`jarvis/api/chat.py`、`jarvis/services/ai/router.py`、provider adapters、`jarvis/core/tool_registry.py`、`jarvis/core/tool_parser.py`
> 对应代码版本：HEAD (`c4569a2` 之后的 `main`)

---

## 0. 一句话总结

Jarvis 的 agent loop 由**三层职责清晰分离**的模块组成：

1. **`AgentLoopRunner`**（`jarvis/core/agent_loop.py`, 475 行）— 公共工具迭代引擎，单一职责"Phase 1 之后的 assistant/tool_result 回填 + 工具并行/去重/迭代 hint"。**三处入口共用**一份逻辑。
2. **`ChatEngine`**（`jarvis/core/chat_engine.py`, 1240 行）— 业务编排层，负责会话/上下文/Prompt 注入/Phase 1 调 LLM（流式/非流式），**Phase 2+ 委派给 `AgentLoopRunner`**。
3. **`AIRouter`** + provider adapters（`jarvis/services/ai/...`）— 模型/协议分发层，把 `model_id + provider_protocol` 解到具体 `AIClient`，由 client 自己负责把 SSE 解析成统一的事件流。

Stream 接口的核心特征：**Phase 1 流式（首字延迟优化）+ Phase 2+ 异步迭代（工具/迭代可控）**，SSE 事件类型是前端契约。

---

## 1. 模块拓扑

```
                          ┌──────────────────────────────────────────────┐
   POST /api/chat/stream  │ jarvis/api/chat.py                            │
   ─────────────────────► │   ├─ ChatRequest / ChatResponse              │
                          │   ├─ chat_stream(request)  ── SSE endpoint   │
                          │   │     ├─ push_token_events()               │
                          │   │     │   └─ TTS 触发 (F5-TTS / 浏览器降级) │
                          │   │     ├─ flush_tail_events()                │
                          │   │     └─ event_generator()                 │
                          │   │          ├─ "status: thinking"           │
                          │   │          ├─ 调 ChatEngine.stream_chat*()  │
                          │   │          │   ↓ yields str                │
                          │   │          │      ├─ token chunk           │
                          │   │          │      └─ "{json}" tool event   │
                          │   │          ├─ "audio_done"                 │
                          │   │          └─ "done"                       │
                          │   └─ chat() / list_models()                  │
                          └────────────────┬─────────────────────────────┘
                                           ▼
                          ┌──────────────────────────────────────────────┐
                          │ jarvis/core/chat_engine.py (1240 行)         │
                          │   ├─ __init__ 装配 AgentLoopRunner + Router  │
                          │   ├─ chat()              — 非流式入口       │
                          │   ├─ stream_chat()       — 流式入口 (DB 拉)  │
                          │   ├─ stream_chat_with_messages() — 流式入口 │
                          │   │      (前端传 history)                    │
                          │   ├─ ContextManager.build_messages()         │
                          │   ├─ SubagentOrchestrator (tool=subagent)    │
                          │   ├─ _build_system_prompt()                  │
                          │   └─ _save_conversation_to_file()            │
                          │                                              │
                          │   Phase 1 (chat/stream_chat*):                │
                          │     router.chat(messages, stream=…)         │
                          │     ↓                                        │
                          │   Phase 2+ (有 tool_use 时):                 │
                          │     runner.run_iterations(…)  ←──┐          │
                          └────────────────┬─────────────────┼──────────┘
                                           ▼                 │
                          ┌─────────────────────────────────┼──────────┐
                          │ jarvis/core/agent_loop.py (475 行)           │
                          │   AgentLoopRunner.run_iterations()           │
                          │     while tool_uses and iter < max:           │
                          │       ├─ inject iteration hint (iter > 2)    │
                          │       ├─ _build_assistant_turn()  ★核心修复 │
                          │       ├─ _dedup()                           │
                          │       ├─ yield "tool_call"                   │
                          │       ├─ _exec_tools() (parallel)            │
                          │       ├─ _append_tool_result()               │
                          │       ├─ inject stop hint (iter == max)      │
                          │       ├─ router.chat(stream=False)  ←────────┘
                          │       └─ extract next tool_uses
                          │     yield AgentLoopResult
                          └────────────────┬─────────────────────────────┘
                                           ▼
                          ┌──────────────────────────────────────────────┐
                          │ jarvis/services/ai/router.py (AIRouter)      │
                          │   ├─ chat()           ── 非流 + fallback    │
                          │   ├─ chat_stream()    ── 纯文本流 (旧)     │
                          │   ├─ chat_stream_full() ── 事件流 (新)      │
                          │   └─ _get_client[_with_instance]()          │
                          └────────────────┬─────────────────────────────┘
                                           ▼
                          ┌──────────────────────────────────────────────┐
                          │ providers/*.py                               │
                          │   AnthropicAdapter (/v1/messages, SSE)       │
                          │     ├─ chat()                               │
                          │     ├─ chat_stream_full()  ← 事件流解析      │
                          │     └─ vision_analyze() / transcribe_audio() │
                          │   OpenAIAdapter   (/v1/chat/completions)     │
                          │     ├─ provider_protocol = "openai"          │
                          │     ├─ chat()  message.tool_calls → blocks   │
                          │     └─ chat_stream_full()  delta 拼装        │
                          │   OllamaAdapter  (兼容 Anthropic /v1/messages)│
                          │   MiniMaxAdapter (Anthropic-compatible)      │
                          └──────────────────────────────────────────────┘
```

---

## 2. 三个入口的对照表

| 入口 | 行号 (chat_engine.py) | Phase 1 | Phase 2+ | 持久化时机 | 主题生成 |
|------|----------------------|---------|----------|-----------|---------|
| `chat()` | 237-492 | `router.chat(stream=False)` 一次 | `runner.run_iterations(...)` | 加 assistant 后写 DB + JSON | 同步（首轮）|
| `stream_chat()` | 494-783 | `router.chat_stream_full(...)` 流式收事件 | 同上 | 收完所有事件后写 | 异步（流式）|
| `stream_chat_with_messages()` | 785-1069 | 同 `stream_chat` | 同上 | 同上 | 异步（流式）|

**三者共用 `AgentLoopRunner.run_iterations`** — 这是 PR2 (`c4569a2`) 的核心改动。

差异：

- `chat()` Phase 1 是**非流式** → `response.content` / `response.content_blocks` 一次性拿到 → 走 `AgentLoopRunner._extract_tool_uses` 决定是否进 Phase 2
- 两个流式入口 Phase 1 是**事件流** → 手动解析 `thinking_start/thinking/thinking_end/text/tool_use_start/tool_use_delta/tool_use_end/message_stop` → 累积 `content_blocks` / `tool_uses` → 决定是否进 Phase 2
- `stream_chat()` 用 DB 里的 history；`stream_chat_with_messages()` 用调用方传入的 history（过滤掉 system）

---

## 3. `AgentLoopRunner` 核心逻辑深读

### 3.1 配置

```python
# jarvis/core/agent_loop.py:47-61
@dataclass
class AgentLoopConfig:
    max_iterations: int = 8               # PR2 从 5 提到 8, 由 ChatEngine 从 Settings 注入
    provider_protocol: str = "anthropic"  # "anthropic" | "openai"
    parallel_tool_exec: bool = True       # asyncio.gather
    dedup_tool_calls: bool = True         # 同 (tool, input) 只执行第一次
    inject_iteration_hint: bool = True    # iter > 2 时塞 user 提示
    inject_stop_hint_on_max: bool = True  # iter == max 时强制停止 hint
```

运行时注入点：`chat_engine._apply_runtime_settings()` (186-206 行)，从 `memory_store.get_all_settings()["tool_loop_max_iterations"]` 读 1-20 之间的整数，clamp 后写回 `runner.config.max_iterations` 和 `subagent_orchestrator.max_iterations`。**设置改了下一次对话立刻生效**，无需重启。

`provider_protocol` 由 `_resolve_provider_protocol(instance)` (118-130 行) 决定：

```
ollama / anthropic → "anthropic"  (tool_use blocks + user tool_result)
openai  / minimax  → "openai"     (tool_calls + role=tool)
```

### 3.2 `run_iterations` 主循环

```python
# jarvis/core/agent_loop.py:133-266
async def run_iterations(
    self, messages, router, *,
    model, instance,
    current_text, current_thinking="",
    current_content_blocks=None, current_tool_uses=None,
) -> AsyncIterator[dict]:
    iteration = 1
    tool_executions = []
    text = current_text
    thinking = current_thinking
    tool_uses = list(current_tool_uses or [])

    while tool_uses and iteration < self.config.max_iterations:
        iteration += 1
        yield {"type": "tool_iter", "iteration": iteration, "max": self.config.max_iterations}

        # 1) iter > 2 时注入 hint
        if self.config.inject_iteration_hint and iteration > 2:
            self._inject_hint(messages, iteration, max)

        # 2) ★ 注入 assistant turn (含 tool_use 块) — 修复 chat() 漏写 bug
        assistant_turn = self._build_assistant_turn(current_content_blocks, current_text)
        messages.append(assistant_turn)

        # 3) 去重
        if self.config.dedup_tool_calls:
            unique_uses, skipped_uses = self._dedup(tool_uses)
            for sk in skipped_uses:
                yield {"type": "tool_skipped", "tool": sk.get("name"), "reason": "duplicate"}
        else:
            unique_uses = tool_uses

        # 4) 执行 (并行 / 串行)
        for tu in unique_uses:
            yield {"type": "tool_call", "tool": ..., "action": ..., "params": ...}
        exec_results = await self._exec_tools(unique_uses)

        # 5) tool_result 回填 + 推送 SSE
        for tu, er in zip(unique_uses, exec_results):
            tool_call = self._to_tool_call(tu)
            self._append_tool_result(messages, tool_call, er)   # ★ 协议分发
            tool_executions.append(...)
            yield {"type": "tool_result", "tool": ..., "status": ..., "result": er}

        # 6) 末轮 stop hint
        if iteration == self.config.max_iterations and self.config.inject_stop_hint_on_max:
            self._inject_stop_hint(messages)

        # 7) 下一轮非流式 LLM
        response = await router.chat(messages, model=model, instance=instance, stream=False)
        text = response.content or ""
        thinking = response.thinking or ""
        current_content_blocks = response.content_blocks or []
        tool_uses = self._extract_tool_uses(current_content_blocks, text)

    # 终止
    max_reached = iteration >= self.config.max_iterations and bool(tool_uses)
    yield {"type": "result", "result": AgentLoopResult(...)}
```

#### 关键设计点

| 设计点 | 实现 | 修复的 bug |
|--------|------|-----------|
| **assistant turn 注入** | `_build_assistant_turn()` (290-323) | **核心 bug**：原 `chat()` 在 tool_result 之前没写 assistant turn，导致下一轮 LLM 看到孤儿 tool_result → 400/2013 |
| **provider_protocol 分发** | `_build_assistant_turn_openai()` (325-378) + `_append_tool_result()` (380-409) | OpenAI/MiniMax 协议需要 `tool_calls` 数组 + `role=tool`；Anthropic 用 `content: [{type: tool_use}]` + `user` 角色包 `tool_result` |
| **去重** | `_dedup()` (433-451)，SHA1(tool+params) | LLM 偶发重复调用浪费算力 |
| **并行执行** | `_exec_tools()` (453-463)，`asyncio.gather` | 多 tool 场景下减少 wall-clock |
| **iteration hint** | iter > 2 才注入（iter=2 是常规 Phase 2） | 给 LLM 节奏感，不在第 2 轮就喧宾夺主 |
| **stop hint** | iter == max 时注入 | 防止 max 边界 LLM 仍想调工具 |

### 3.3 协议分发细节（OpenAI vs Anthropic）

`_build_assistant_turn_openai()` (325-378) 处理 OpenAI 协议的几个细节：

1. **text** → `msg["content"]` (str，可能 None)
2. **thinking** → OpenAI 没有原生 reasoning 字段，**拼到 content 前面 + `[思考]` 前缀**
3. **tool_use** → `msg["tool_calls"] = [{id, type:"function", function:{name, arguments: <json str>}}]`
4. `arguments` 必须是 JSON 字符串，不是 dict（OpenAI 协议要求）

`_append_tool_result()` (380-409) 的差异：

```python
if provider_protocol == "openai":
    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})
else:  # anthropic
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_call.id, "content": content}
    ]})
```

### 3.4 Tool ID 兜底（健壮性）

`ToolCall.__post_init__` (tool_parser.py:34-40) 在 id 缺失时生成稳定哈希 `tc-<sha1[:12]>`。**这是兜底** —— 正常路径下 id 由 Anthropic/Ollama 在 `tool_use_start` 事件中给，OpenAI 在 `delta.tool_calls[].id` 给。

`_to_tool_call()` (agent_loop.py:280-288) 把 content_block 形态的 tool_use 转 `ToolCall` 时显式传入 id，让兜底逻辑生效。

---

## 4. Phase 1：LLM 调用的两种形态

### 4.1 非流式（`chat()` 用）

```python
# chat_engine.py:322-333
response = await self.router.chat(
    messages, model=model, instance=instance, stream=False
)
response_text = response.content or ""
response_thinking = response.thinking or ""
content_blocks = response.content_blocks or []
tool_uses = AgentLoopRunner._extract_tool_uses(content_blocks, response_text)
```

`router.chat()` 内部走 fallback chain（如果 instance 绑定则跳过 chain 直接调 `_get_client_with_instance`）。

### 4.2 流式（`stream_chat*` 用）

```python
# chat_engine.py:581-622 (stream_chat)
async for event in self.router.chat_stream_full(messages, model=model, instance=instance):
    etype = event.get("type", "")
    if etype == "thinking_start": yield json.dumps(...)
    elif etype == "thinking": ...    # 直接 yield token chunk
    elif etype == "text": ...        # ★ 关键：直接 yield 原 chunk 给 API 层
    elif etype == "tool_use_start": current_tool = {...}
    elif etype == "tool_use_end":   # 累积 input_json 拼成完整 input
        current_tool["input"] = event["input"]
        tool_uses.append(current_tool)
    elif etype == "message_stop": break
```

`router.chat_stream_full()` (router.py:107-119) 是个简单透传，调 `client.chat_stream_full(messages)`。

#### 4.2.1 Anthropic adapter 的 SSE 解析

```python
# anthropic.py:110-202
async def chat_stream_full(self, messages) -> AsyncIterator[dict]:
    # payload 含 tools=tool_registry.build_anthropic_tools()
    async with self.client.stream("POST", "/v1/messages", json=payload) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                evt_type = data.get("type", "")

                if evt_type == "message_start": yield {"type": "message_start", ...}
                elif evt_type == "content_block_start":
                    block_type = data["content_block"]["type"]
                    if block_type == "thinking": yield {"type": "thinking_start", ...}
                    elif block_type == "text": yield {"type": "text_start", ...}
                    elif block_type == "tool_use":
                        # 记录 name/id, 准备接收 input_json_delta
                elif evt_type == "content_block_delta":
                    if current_block_type == "thinking" and delta_type == "thinking_delta":
                        yield {"type": "thinking", "content": delta["thinking"]}
                    elif current_block_type == "text" and delta_type == "text_delta":
                        yield {"type": "text", "content": delta["text"]}
                    elif current_block_type == "tool_use" and delta_type == "input_json_delta":
                        tool_input_parts.append(delta["partial_json"])
                        yield {"type": "tool_use_delta", "partial_json": ...}
                elif evt_type == "content_block_stop":
                    if current_block_type == "tool_use":
                        input_data = json.loads("".join(tool_input_parts))
                        yield {"type": "tool_use_end", "name": ..., "id": ..., "input": input_data}
                elif evt_type == "message_stop": yield {"type": "message_stop", ...}
```

要点：
- Anthropic SSE 的 `tool_use` 块通过 `input_json_delta` **增量流式**传输参数 JSON，前端可选择性推送
- `chat_stream()` (204-209) 是 backward-compat 简化版，只 yield `thinking`/`text` 的 content

#### 4.2.2 OpenAI adapter 的 SSE 解析（PR3）

```python
# openai.py:139-259
async def chat_stream_full(self, messages) -> AsyncIterator[dict]:
    # 按 index 累积 tool_call 增量
    tc_buf: dict[int, dict] = {}  # {index: {id, name, args_parts: [...]}}
    in_text = False

    async for line in resp.aiter_lines():
        # delta.tool_calls 是数组, 每个元素含 index
        # - index: 同一调用跨多个 chunk 的拼接索引
        # - id: 第一次出现
        # - function.name: 第一次出现
        # - function.arguments: 增量 JSON 字符串
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            if idx not in tc_buf:
                tc_buf[idx] = {"id": "", "name": "", "args_parts": []}
                yield {"type": "tool_use_start", "name": ..., "id": ...}
            args_delta = (tc.get("function") or {}).get("arguments")
            if args_delta:
                tc_buf[idx]["args_parts"].append(args_delta)
                yield {"type": "tool_use_delta", "partial_json": args_delta}

    # 流结束 — flush text_end + 拼装所有 tool_use_end
    for idx in sorted(tc_buf.keys()):
        full_json = "".join(tc_buf[idx]["args_parts"])
        input_data = json.loads(full_json)
        yield {"type": "tool_use_end", "name": ..., "id": ..., "input": input_data}
    yield {"type": "message_stop", ...}
```

要点：
- **统一事件格式**：Anthropic 和 OpenAI adapter 输出的事件类型完全一致（`thinking` / `text` / `tool_use_start` / `tool_use_delta` / `tool_use_end` / `message_stop`），上层 ChatEngine / AgentLoopRunner 不知道协议差异
- `_openai_tool_calls_to_blocks()` (21-50) 在 `chat()` 路径把 `message.tool_calls` 转 `content_blocks` (Anthropic 形态) — **AgentLoopRunner 统一消费**

---

## 5. Stream 接口 SSE 事件契约

### 5.1 端点

`POST /api/chat/stream`（`jarvis/api/chat.py:70-259`）

请求体（`ChatRequest`）：
```python
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True
    force_refresh_models: bool = False
    messages: Optional[list[dict]] = None   # 传完整历史走 stream_chat_with_messages
    provider_id: Optional[str] = None
    enable_tts: bool = True
```

### 5.2 SSE 事件类型清单

`EventSourceResponse` 返回的是 `text/event-stream`，每个事件带 `event` 字段（用作 event name）和 `data` 字段（JSON 字符串）。

| Event name | 触发时机 | data 内容 | 来源 |
|-----------|----------|----------|------|
| `status` | 流开始 / 工具检测 / 工具迭代计数 | `{"type": "status", "content": "thinking" \| "tool_detected" \| "tool_iter_N"}` | `event_generator` |
| `token` | 文本 token chunk | `{"type": "token", "content": "<chunk>"}` | `push_token_events` |
| `thinking` | thinking chunk | `{"type": "thinking_start\|thinking\|thinking_end", "content": ...}` | ChatEngine 直接 yield |
| `tool` | 工具调用事件 (`tool_iter` / `tool_call` / `tool_skipped` / `tool_result`) | 来自 AgentLoopRunner 的 event JSON | ChatEngine 流式转发 |
| `audio` | TTS 流式 PCM 块 | `encode_pcm_chunk(idx, pcm)` 编码 | `push_token_events` / `flush_tail_events` |
| `audio_done` | TTS 完成 | `{"type": "audio_done", "sentences": N, "sample_rate": 24000, ...}` | `event_generator` 末尾 |
| `tts_fallback` | TTS 不可用，提示前端走浏览器 | `{"type": "tts_fallback", "text": "..."}` | `push_token_events` |
| `topic_update` | 首轮对话主题生成 | `{"type": "topic_update", "topic": "..."}` | `_generate_and_yield_topic` |
| `done` | 全部结束 | `{"type": "done", "content": "<full_response>", "conversation_id": "..."}` | `event_generator` 末尾 |
| `error` | 异常 | `{"type": "error", "content": "<err msg>"}` | `event_generator` 异常分支 |

### 5.3 SSE 分支路由（chat.py:185-201）

```python
async for content in mediator.chat_engine.stream_chat_with_messages(...):
    if content.startswith("{"):
        # ChatEngine 包装的 JSON 事件
        evt = json.loads(content)
        evt_type = evt.get("type", "unknown")
        sse_event = "tool" if evt_type.startswith("tool") else "token"
        yield {"event": sse_event, "data": content}
    else:
        # ChatEngine 直接 yield 的纯文本 chunk
        full_response += content
        async for ev in push_token_events(content):
            yield ev
```

**契约约定**：
- 字符串以 `{` 开头 → 是 JSON 事件包（`tool_call` / `tool_result` / `tool_iter` / `tool_skipped` / `thinking_*` / `topic_update`）
- 否则是文本 token → 走 `push_token_events` 触发 TTS
- 工具事件统一走 `event="tool"`，前端按 `data.type` 细分

### 5.4 TTS 集成

`push_token_events` (chat.py:92-127)：
1. 把 token 累到 `sentence_buf`
2. 用 `_find_split()` 按标点切句（min_chars / max_chars 阈值）
3. 切到完整句 → 调 `f5_tts.synthesize_to_pcm()` 异步 yield PCM → SSE `audio` 事件
4. F5-TTS 不可用 → SSE `tts_fallback` 事件，前端走浏览器 `SpeechSynthesis`

`flush_tail_events` (chat.py:129-156)：流结束后清空残余 buffer。

`tts_disabled = not enable_tts` 时：**完全不触发**任何 TTS/fallback（短路 + 清空 buffer）。

---

## 6. Tool Registry & 执行

### 6.1 内置工具

`jarvis/core/tool_registry.py` 注册 7 个工具：

| 工具 | 用途 | 关键参数 |
|------|------|---------|
| `file` | 文件读写编辑删除 | `action: read/write/edit/delete/list/mkdir/exists`, `path`, `content` |
| `bash` | 执行 shell | `command`, `timeout`, `cwd` |
| `browser` | Playwright 自动化 | `action: navigate/click/type/screenshot/evaluate` |
| `desktop` | pyautogui 桌面控制 | `action`, `x`, `y`, `text` |
| `api` | HTTP 请求 | `method`, `url`, `headers`, `body` |
| `tool` | MCP 工具转发 | `name`, `params` |
| `subagent` | 委派子任务 | `role: researcher/coder/reviewer/summarizer/planner/general`, `task`, `context`, `mode: sequential/parallel/map_reduce`, `tasks`, `reduce_prompt` |

### 6.2 协议转换

```python
# tool_registry.py:233-287
def build_anthropic_tools(self) -> list[dict]:
    # → {"name", "description", "input_schema": {properties, required}}

def build_openai_tools(self) -> list[dict]:
    # → {"type": "function", "function": {name, description, parameters: {properties, required}}}
```

两个函数输出形态不同，但**都从同一份 ToolDefinition 注册表生成**。

### 6.3 Tool 执行

`AgentLoopRunner._exec_one()` (465-475) 包了一层 try/except：
```python
async def _exec_one(self, tu: dict) -> Any:
    tool_name = tu.get("name", "")
    params = tu.get("input", {}) or {}
    try:
        step = Step(tool=tool_name, params=params)
        return await self.task_executor.execute_step(step)
    except Exception as e:
        logger.error(f"[AgentLoop] tool {tool_name} failed: {e}")
        return {"status": "error", "message": str(e)}
```

**异常不会中断循环**，而是包成 `{"status": "error", "message": ...}` 回填到 `tool_result`，让 LLM 看到失败并决定下一步。

`_exec_tools()` (453-463) 在 `len > 1` 时用 `asyncio.gather(..., return_exceptions=False)` 并行执行。**注意 `return_exceptions=False`**：单个工具 raise 仍会传播，但被 `_exec_one` 兜底后实际拿到的是 dict，不会再抛。

---

## 7. ChatEngine 三处入口的 Phase 1 差异

### 7.1 `chat()` 的工具检测路径

```python
# chat_engine.py:322-366
response = await self.router.chat(messages, model=model, instance=instance, stream=False)
response_text = response.content or ""
content_blocks = response.content_blocks or []
tool_uses = AgentLoopRunner._extract_tool_uses(content_blocks, response_text)

if not tool_uses:
    # 直接返回 + 持久化 + 主题生成
    return {"text": ..., "topic": ...}

# 否则调 runner.run_iterations (chat() 不消费 event, 只取 final_result)
```

**关键差异**：原 bug 在这一行 — 旧代码直接 `messages.append(tool_result)`，没有先 append assistant turn。新代码全部走 runner，由 `_build_assistant_turn()` 在 `messages.append(assistant_turn)` 之后才 append tool_result，**修复了 400/2013**。

### 7.2 `stream_chat()` 的事件流消费

```python
# chat_engine.py:581-622
streamed_text = ""
streamed_thinking = ""
tool_uses = []
content_blocks = []
current_tool = None

async for event in self.router.chat_stream_full(messages, model=model, instance=instance):
    etype = event.get("type", "")
    if etype == "thinking_start": yield json.dumps({"type": "thinking_start", ...})
    elif etype == "thinking": ...
    elif etype == "thinking_end":
        if streamed_thinking:
            content_blocks.append({"type": "thinking", "thinking": streamed_thinking})
    elif etype == "text":
        streamed_text += chunk
        yield chunk  # ★ 直接流式输出到前端
    elif etype == "tool_use_start":
        current_tool = {"type": "tool_use", "name": event["name"], "id": event["id"], "input": {}}
        yield json.dumps({"type": "status", "content": "tool_detected"})
    elif etype == "tool_use_end":
        current_tool["input"] = event["input"]
        tool_uses.append(current_tool)
        content_blocks.append(current_tool)
    elif etype == "message_stop": break
```

`current_tool` 在 `tool_use_start` 初始化，`tool_use_delta` 期间累积（虽然这里 ChatEngine 不直接 yield delta，因为前端不需要 — Anthropic 的 input_json_delta 由 client 内部拼成完整 JSON 后只 yield `tool_use_end`）。

**`content_blocks` 在 Phase 1 末尾的形态**：
```python
[
    {"type": "thinking", "thinking": "..."},
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}},
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}},
    {"type": "text", "text": "..."},  # 流末尾追加
]
```

这个列表就是 `runner.run_iterations(current_content_blocks=...)` 入参，runner 用来构造下一轮的 assistant turn。

### 7.3 后续流式输出

Phase 2+ 跑完后，`final_response` 可能与 Phase 1 文本不同（因为 LLM 看了 tool_result 后改了主意）。ChatEngine 把**增量部分**再流式推给前端：

```python
# chat_engine.py:766-769
if final_response != phase1_text:
    for chunk in self._chunk_text(final_response, 8):
        yield chunk
```

`_chunk_text(text, size=8)` 按 8 字符切片，模拟 token 流。前端收到时已经 `done` 事件过去了 — 这部分增量会触发前端 `done reconcile` 逻辑（参见 commit `debd13a`）。

---

## 8. 上下文管理（前置阶段）

Phase 1 调 LLM 之前，三处入口都过一遍 `ContextManager.build_messages()`：

```python
# chat_engine.py:303-311
ctx_result = await self.context_manager.build_messages(
    system_prompt=system_prompt,
    history=history_dicts,
    current_user_input=user_input,
    memory_retriever=self.memory.retrieve,
    model_id=model,
    memory_top_k=3,
    conversation=self.current_conversation,
)
messages = ctx_result["messages"]
```

`ContextManager` 做三件事（见 CLAUDE.md 的 Context Management 章节）：
1. 检索相关记忆（top_k=3）→ 注入到 system_prompt 末尾
2. 按 token 预算裁剪对话历史（替代旧硬编码 `get_history(limit=10)`）
3. 拼成 `[{system}, {history...}, {user}, ...]`

**stats 字段**：`history_in` / `history_out` / `dropped` / `memory_chunks` / `tokens_estimate` / `budget_available` — 都打 debug 日志。

---

## 9. 测试覆盖

`tests/test_chat_engine.py` 共 907 行，其中 `TestAgentLoop` 类（587-906）6 个测试（PR2 新增）：

| 测试 | 验证点 |
|------|--------|
| `test_assistant_turn_precedes_tool_result` | **核心 bug 修复**：messages 序列里 assistant turn 必须在 tool_result 之前 |
| `test_dedup_duplicate_tool_calls` | 同 (tool, input) 的二次调用被 skip，只推 `tool_skipped` 事件 |
| `test_iteration_hint_injected_after_iter2` | iter=3 才有 hint，iter=2 没有 |
| `test_parallel_tool_execution` | `len > 1` 时 `asyncio.gather` 并行 |
| `test_stop_hint_at_max_iterations` | iter == max 时注入 `[系统提示] 已达最大工具迭代次数` |
| `test_no_tool_uses_returns_immediately` | Phase 1 无 tool_use → 跑 0 次迭代，只 yield 一个 `result` 事件 |

`TestChatEngine` 原有 25 个测试仍覆盖 chat/stream_chat/stream_chat_with_messages 行为。

---

## 10. 关键不变量与边界

### 10.1 三处入口共用 runner 的代价

**优点**：
- 修 bug 一处生效（PR2 同时修了 chat/stream_chat/stream_chat_with_messages）
- 行为一致：iteration hint / dedup / parallel / stop hint 都不会偏差

**代价**：
- 三个入口 Phase 1 输出形态不同（chat 是 dict，stream 是 str/JSON），但 Phase 1 末尾必须把"text + content_blocks + tool_uses"三个值塞进 runner 的入参 — **这是 ChatEngine 的责任，不是 runner 的责任**
- ChatEngine 自己决定要不要 yield runner 的中间事件（chat 完全忽略，stream 全部转 SSE）

### 10.2 assistant turn 的协议分界

`_build_assistant_turn()` 按 `provider_protocol` 分两路。**Anthropic path 把所有 content_block 直接序列化**（包括 `thinking` 块），`openai` path 则把 thinking 拼到 content 前面加 `[思考]` 前缀。

这意味着：
- Anthropic: 下一轮 LLM 看到原生 thinking block → 可正确分离 reasoning vs answer
- OpenAI/MiniMax: 下一轮 LLM 看到一段 `[思考]\n...` 文本 → reasoning 和 answer 混在一起

**已知缺陷**（PR3 已部分缓解，PR4+ 待优化）：
- MiniMax 是 Anthropic-compatible，理应走 anthropic path，但被 `_resolve_provider_protocol` 强制分到 openai path。详见 README 的"ProviderInstance 协议分发"。
- OpenAI path 的 `[思考]` 前缀会被 LLM 当作 user 说的话，可能污染后续回答。

### 10.3 stop hint 时机

```python
if iteration == self.config.max_iterations and self.config.inject_stop_hint_on_max:
    self._inject_stop_hint(messages)
```

hint 在**注入 tool_result 之后**追加，下一轮 LLM 调接口时才能看到。但此时如果 LLM 又回 tool_use，runner 会再走一轮 iteration + 1，但 `iteration < max` 已不满足 → 直接终止 → `max_iterations_reached=True` → `final_text` 是这一轮的 `response.content`。

**隐患**：hint 在 tool_result 之后追加，但 stop hint 之前 LLM 已经决定要调工具了 — hint 可能无效。**实际行为**是 LLM 拿到 hint 后**第二轮才**收敛，但已经被 max 截断。

### 10.4 内容回填的对称性

Anthropic 协议 tool_result 是 `user` 角色包 `[{type:tool_result, tool_use_id, content}]`。意味着一个 assistant turn + 一个 user turn 形成**一组**（一个 tool_use 对应一个 tool_result）。

如果 LLM 在同一轮调了 N 个工具，runner 会塞 N 个独立的 `tool_result` user turn。**Anthropic API 要求 tool_result 必须对应前一个 assistant turn 的 tool_use** — 多个 user turn 顺序排列是允许的，但要求 `tool_use_id` 一一对应。

`_append_tool_result()` 直接 append，每次独立加 — 没有合并 — 行为正确但 messages 列表增长快。

### 10.5 ToolExecution 持久化形态

```python
# chat_engine.py:391-402
elif etype == "tool_call":
    tool_call_message = {"tool": event["tool"], "action": event["action"], "params": event["params"]}
    self.current_conversation.add_message("tool", json.dumps(tool_call_message))
```

**注意**：写进对话的是 `role="tool"` + JSON 字符串 content。前端 ChatMessage.vue 看到 `role=="tool"` 就显示工具调用的可折叠卡片。`role="tool_result"` 是工具**结果**的角色 — 两套角色在 Conversation 列表里都看得到。

### 10.6 Topic 生成时机差异

- `chat()`: Phase 1/2+ 全部结束后**同步**生成主题（阻塞最后 return）
- `stream_chat*`: Phase 1/2+ 全部结束后**流式生成**主题（async for yield `topic_update` 事件）

流式路径不阻塞响应延迟，但前端要在 `done` 事件之后还能继续接收 `topic_update` — 前端代码按 `event==="topic_update"` 单独处理（参见 Sidebar.vue 的 topic 显示）。

### 10.7 max_iterations 的双重夹紧

1. Settings UI 限制 1-20（前端）
2. `chat_engine._apply_runtime_settings()` 再 clamp 一次（`max(1, min(20, n))`，后端）

如果用户从 Settings 改到 30，前端会卡在 20；改到 0 会卡在 1。**这是一道防御**。

---

## 11. Stream 接口的 TTFB 优化要点

Phase 1 流式的核心目标是**首字延迟**：

1. **直接 yield 原 chunk**（不包 JSON）→ `event_generator` 把它当字符串处理 → 走 `push_token_events` → SSE `token` 事件
2. **JSON 事件路径**（`content.startswith("{")`）→ `event="tool"` → 不经过 TTS
3. **status 事件优先** → 流开始立刻 `{"type": "status", "content": "thinking"}` 让前端显示加载态

`push_token_events` 的 TTS 触发是**增量切句**：
- 每个 token 累到 `sentence_buf`
- 每收到一个 token 后检查是否能切句（`_find_split` 找标点 + 长度阈值）
- 能切 → 立即触发 F5-TTS 合成 → SSE `audio` 事件推 PCM
- 不能切 → 继续累积

**降级契约**（CLAUDE.md 有详细）：
- F5-TTS 不可用 → SSE `tts_fallback` → 前端走 `speechSynthesis.speak()`
- `enable_tts=false` → 整个 `push_token_events` / `flush_tail_events` 短路，不推任何 TTS/fallback 事件
- `enable_tts=false` 时 `audio_done` 事件也不推（chat.py:222-234）

---

## 12. 改进建议（基于代码读到的迹象）

> 不是 bug 列表，是观察到的可优化点。

1. **`_exec_tools` 的 `return_exceptions=False` 与 `_exec_one` 兜底重复** — `_exec_one` 已经 try/except 兜底成 `{"status": "error"}`，`gather` 永远不会 raise。`return_exceptions=False` 等于无效。可改成 `True` 防御未来重构。

2. **`chat()` 没有 yield `topic_update` 事件** — 只 `return {text, topic}`，前端用 REST 路径拿主题。如果用户从流式切到非流式，前端 topic 显示逻辑可能有差异。是否对齐两路？

3. **OpenAI path 的 `[思考]` 前缀污染** — 已在 10.2 提到。短期方案：OpenAI/MiniMax 走 `provider_protocol="openai"` 时跳过 thinking 持久化（thinking 块不入 messages）；或让 MiniMax 走 anthropic path（它确实是 Anthropic-compatible）。

4. **stop hint 时机** — 已在 10.3 提到。可考虑改成"在 LLM 调用前"注入，prompt 当成下一轮的引导。但需要重构 — 当前 hint 是 user 角色 message，挪到 system 比较干净。

5. **`agent_loop_runner.config` 是共享可变状态** — `chat_engine._apply_runtime_settings()` 改 `runner.config.max_iterations`，如果同时有两个请求（chat + stream），会竞争。Python asyncio 是单线程，所以不会真出错，但代码读起来别扭。可改成每次调用 `run_iterations` 时传 `config` 参数。

6. **`chat_stream_full` 的 tool_use_delta 不转 SSE** — Anthropic/OpenAI 都 yield `tool_use_delta`，但 ChatEngine 不消费（只在 client 内部累积 JSON 拼成完整 input）。这对前端不可见是 OK 的，但增加了一次解析开销。如果想给前端更细粒度的"工具参数实时显示"，可加一路 SSE `tool_input_delta` 事件。

7. **`messages.append` 是 in-place mutation** — `AgentLoopRunner.run_iterations(messages, ...)` 直接改调用方的 messages 列表。这是隐式约定 — ChatEngine 每次调 LLM 前 rebuild messages，所以副作用可控。但如果未来加入 message 复用缓存，这里会爆。

---

## 13. 关键源码索引

| 关注点 | 文件 | 行号 |
|--------|------|------|
| AgentLoopRunner 主类 | `jarvis/core/agent_loop.py` | 108-476 |
| AgentLoopConfig | 同上 | 47-61 |
| run_iterations 主循环 | 同上 | 133-266 |
| `_build_assistant_turn` (Anthropic path) | 同上 | 290-323 |
| `_build_assistant_turn_openai` | 同上 | 325-378 |
| `_append_tool_result` (协议分发) | 同上 | 380-409 |
| `_dedup` | 同上 | 433-451 |
| `_exec_tools` / `_exec_one` | 同上 | 453-475 |
| `_resolve_provider_protocol` | `jarvis/core/chat_engine.py` | 118-130 |
| `_apply_runtime_settings` | 同上 | 186-206 |
| `chat()` (非流式) | 同上 | 237-492 |
| `stream_chat()` | 同上 | 494-783 |
| `stream_chat_with_messages()` | 同上 | 785-1069 |
| `_generate_and_yield_topic` | 同上 | 1071-1096 |
| `_chunk_text` (增量流) | 同上 | 1138-1142 |
| ChatRequest/ChatResponse | `jarvis/api/chat.py` | 16-37 |
| `chat_stream` SSE 端点 | 同上 | 70-259 |
| `push_token_events` | 同上 | 92-127 |
| `flush_tail_events` | 同上 | 129-156 |
| `event_generator` | 同上 | 158-257 |
| AIRouter.chat_stream_full | `jarvis/services/ai/router.py` | 107-119 |
| AIRouter._get_client_with_instance | 同上 | 42-57 |
| AnthropicAdapter.chat_stream_full | `jarvis/services/ai/providers/anthropic.py` | 110-202 |
| OpenAIAdapter.chat_stream_full | `jarvis/services/ai/providers/openai.py` | 139-259 |
| `_openai_tool_calls_to_blocks` | 同上 | 21-50 |
| ToolCallParser / ToolCall | `jarvis/core/tool_parser.py` | 14-40, 43-127 |
| ToolRegistry.build_anthropic_tools | `jarvis/core/tool_registry.py` | 233-255 |
| ToolRegistry.build_openai_tools | 同上 | 257-287 |
| TestAgentLoop 测试套 | `tests/test_chat_engine.py` | 587-906 |

---

## 14. 一图流（stream_chat 主流程）

```
Client
  │
  │  POST /api/chat/stream
  ▼
┌─ FastAPI: jarvis/api/chat.py:chat_stream ─────────────────────────┐
│  1. yield "status: thinking"                                       │
│  2. async for content in ChatEngine.stream_chat():                  │
│       ├─ content = "..." (text chunk)                              │
│       │    └─ push_token_events(content)                            │
│       │         ├─ SSE "token"                                     │
│       │         └─ _find_split() → F5-TTS → SSE "audio"           │
│       │                OR SSE "tts_fallback"                       │
│       └─ content = "{...}" (JSON)                                  │
│            └─ SSE "tool" (event name) with data=content            │
│  3. flush_tail_events()  → SSE "audio" / "tts_fallback"           │
│  4. SSE "audio_done"                                               │
│  5. SSE "done"                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─ ChatEngine.stream_chat (chat_engine.py:494-783) ─────────────────┐
│  Phase 1:                                                           │
│    router.chat_stream_full(messages, model, instance)                │
│    ├─ AnthropicAdapter / OpenAIAdapter                              │
│    │   解析 SSE → 统一事件流:                                        │
│    │   {type: thinking_start|thinking|thinking_end|text|             │
│    │        tool_use_start|tool_use_delta|tool_use_end|message_stop}│
│    └─ ChatEngine:                                                    │
│         ├─ "thinking" → SSE (json.dumps)                            │
│         ├─ "text" → yield chunk (纯字符串, 走 API 层 push_token)    │
│         └─ "tool_use_end" → 累积 tool_uses + content_blocks         │
│                                                                      │
│  Phase 2+ (有 tool_uses 时):                                         │
│    runner.run_iterations(messages, router, ...,                      │
│       current_text, current_content_blocks, current_tool_uses)       │
│    ├─ yield {"type": "tool_iter"}                                   │
│    ├─ yield {"type": "tool_call"}                                   │
│    ├─ _exec_tools() → asyncio.gather  ──┐                           │
│    ├─ yield {"type": "tool_result"}      │                          │
│    ├─ _append_tool_result() (回填 messages, 协议分发)               │
│    ├─ router.chat(stream=False)         │                           │
│    │   → response.content_blocks / tool_uses                         │
│    └─ ... 直到 tool_uses 空 或 iter == max                          │
│                                                                      │
│  Phase 3 (收尾):                                                     │
│    ├─ _resolve_image_paths (本地图片 → base64)                      │
│    ├─ add_message("assistant", final_text, thinking)               │
│    ├─ memory.save_conversation(...)                                 │
│    ├─ _save_conversation_to_file()                                  │
│    ├─ 增量流式 yield final_text (与 phase1 不同时)                  │
│    └─ 首轮: _generate_and_yield_topic() → SSE "topic_update"        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 15. 总结

**AgentLoopRunner 是 PR2 的核心抽象** — 它把"Phase 1 后的工具循环"从三个入口里抽出来，修了一个会被 Anthropic 报 400/2013 的核心 bug（漏写 assistant turn），并把 iteration hint / dedup / parallel / stop hint / 协议分发这些"应该一致但容易走偏"的逻辑收敛到一处。

**Stream 接口的工程性体现在**：
- **双层事件流**：Phase 1 流式（首字延迟）/ Phase 2+ 异步迭代（工具/迭代可控）
- **统一事件格式**：Anthropic 和 OpenAI adapter 输出同构事件，上层不感知协议
- **清晰边界**：ChatEngine 负责 Phase 1 事件消费 + 持久化 + 主题；AgentLoopRunner 只负责工具循环；API 层负责 SSE 打包 + TTS
- **降级链完整**：F5-TTS → 浏览器 TTS → 静默（`enable_tts=false`）

PR2-4 三次提交的脉络：`c4569a2` 抽 runner 修核心 bug → `32c0463` 加 OpenAI/MiniMax 协议分发 → `db38b3c` 加 max_iterations Settings 控制 + subagent 跟随主对话 → `debd13a` 前端 SSE error 透传 + done reconcile + tool_skipped UI。每次提交都是上一份基线的"补完"，没有出现大规模返工 — 这是好的演进节奏。
