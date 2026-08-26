# 适配层审查 — 前端请求 body → 模型合法 body

> Date: 2026-08-26
> 关联: `frontend-agent-stream.md` (前端 stream 变更计划), PR3 (provider_protocol 分发)

## 链路

```
前端 ChatWindow
  ↓ POST /api/chat/stream {message, messages, model, provider_id, ...}
FastAPI ChatRequest (Pydantic)
  ↓ mediator.chat_engine.stream_chat(messages_history, ...)
ChatEngine
  ↓ context_manager.build_messages(...)
    ├─ _normalize_history (filter tool/tool_result)  ← 严格模式
    ├─ 注入 system prompt + memory
    └─ 裁剪 token 预算
AIRouter.chat(messages)
  ↓ _get_client_with_instance(instance, model)
AnthropicAdapter / OpenAIAdapter / OllamaAdapter / MiniMaxAdapter
  ↓ 直接 POST {messages} 到对应 API
```

## 结论

**有适配层，但分在三处（ContextManager + AgentLoopRunner + Adapter）**，是 Strategy + Pipeline 风格选择。当前**没有单点失败风险**：

1. 进入 adapter 的 messages 永远是 `{role, content}` 字符串（来自 ContextManager 过滤后的 history）
2. AgentLoopRunner 在工具循环内自己构造 provider-aware 的 assistant turn / tool_result — 这是"显式适配"
3. Adapter 自己的 chat() 只吃 `{role, content}` 字符串，不做格式转换 — 这是"隐式契约"

**Adapter 的反向适配**（响应侧）已完整：
- OpenAIAdapter.chat 把 `message.tool_calls` → `AIResponse.content_blocks`（Anthropic 形态）
- OpenAIAdapter.chat_stream_full 把 `delta.tool_calls` SSE → `tool_use_start/delta/end` 事件
- AnthropicAdapter / OllamaAdapter 天然就是 Anthropic 形态

下游 `AgentLoopRunner._extract_tool_uses(content_blocks)` 无需感知 provider。

## 当前适配机制清单

| 位置 | 做什么 | 现状 |
|---|---|---|
| `ContextManager._normalize_history` (jarvis/core/context_manager.py) | history 规整成 `{role, content}` string 形式 | ✅ 严格模式剥光 tool/tool_result |
| `AgentLoopRunner._build_assistant_turn` (jarvis/core/agent_loop.py) | 按 `provider_protocol` 分发 Anthropic / OpenAI 形态 | ✅ PR3 已做 |
| `AgentLoopRunner._append_tool_result` (jarvis/core/agent_loop.py) | 按 `provider_protocol` 分发 tool_result 形态 | ✅ PR2 已做 |
| `ToolRegistry.build_anthropic_tools` / `build_openai_tools` (jarvis/core/tool_registry.py) | 工具 schema 转换 | ✅ PR3 已做 |
| `OpenAIAdapter.chat` (jarvis/services/ai/providers/openai.py) | `message.tool_calls` → `content_blocks`（Anthropic 形态） | ✅ PR3 已做 |
| `OpenAIAdapter.chat_stream_full` (jarvis/services/ai/providers/openai.py) | `delta.tool_calls` SSE → `tool_use_start/delta/end` 事件 | ✅ PR3 已做 |
| `OpenAIMiniMaxAdapter._openai_tool_calls_to_blocks` (jarvis/services/ai/providers/openai.py + minimax.py) | OpenAI 工具调用块 → Anthropic 形态 | ✅ PR3 已做 |

## 风险点（按严重度）

### 🟡 P1 — Provider 切换的中间态

如果用户从 Anthropic 切到 OpenAI 中途：
1. Anthropic 期间的 assistant turn 持久化时是 `{role:assistant, content:"..."}` 文本形式（仅显示用文本） ✅
2. tool/tool_result 都被 `_normalize_history` 在重载时剥掉 ✅
3. **所以实际切换是安全的**（前提是 assistant 内容始终是 plain text）

**隐患**：未来如果把 assistant turn 的 tool_use blocks 也持久化进 history，切换 provider 时旧消息会带 `content: [{type:tool_use, ...}]` 形态直接喂给 OpenAI → 400。当前接口不严密。

### 🟢 P2 — frontend `request.messages` 直接透传

`ChatRequest.messages` 字段直接被 `stream_chat_with_messages(messages_history, ...)` 接收，喂给 context_manager。ChatWindow 已经做了一层过滤：
```javascript
.filter(m => m.role === 'user' || m.role === 'assistant')
.map(m => ({ role: m.role, content: m.content }))
```

但 chatStore 里实际 `assistant` message.content 是纯文本流累加（`currentResponse.value += token`），所以前端转过来的也是 plain text。**安全**。

### 🟢 P2 — Ollama 用 Anthropic 协议但 base_url 不同

`OllamaAdapter` 走 `/v1/messages`（Anthropic 兼容）。provider_protocol 设为 `"anthropic"`。**没问题**，Ollama 实际就是支持 Anthropic Messages API 的。

## 已记录的隐式约定

> **进入 adapter 的 messages 满足以下约束**，违反会导致协议错误：
> 1. role ∈ `{system, user, assistant}`
> 2. content 是字符串，或 `assistant` role 时为 Anthropic 形态的 list（含 thinking/text/tool_use）
> 3. 不得含 `tool` 或 `tool_result` role
> 4. assistant tool_use 块必须配对 tool_result（Anthropic）或 tool_calls 必须配对 role:tool 消息（OpenAI）

**违反约束的修复责任分布**：
- ChatEngine 通过 ContextManager 过滤历史 → 保证 #1、#3
- AgentLoopRunner 构造 in-loop assistant turn / tool_result → 保证 #2、#4

## 未来可选加固

如果未来要严格化（应对 provider 切换持久化等场景），可以加一个显式 Adapter 层：

```python
# jarvis/services/ai/request_adapter.py
class RequestAdapter(ABC):
    @abstractmethod
    def normalize_messages(self, messages: list[dict]) -> list[dict]:
        """把通用 messages 转换成 provider-native 形态."""

class AnthropicRequestAdapter:
    def normalize_messages(self, messages): return messages  # 已是原生

class OpenAIRequestAdapter:
    def normalize_messages(self, messages):
        out = []
        for m in messages:
            if m["role"] == "assistant" and isinstance(m.get("content"), list):
                # 检测 Anthropic-style content blocks → 转 tool_calls
                tool_calls, text_parts = [], []
                for b in m["content"]:
                    if b.get("type") == "tool_use":
                        tool_calls.append({...})
                    elif b.get("type") == "text":
                        text_parts.append(b["text"])
                msg = {"role": "assistant"}
                if text_parts: msg["content"] = "\n".join(text_parts)
                if tool_calls: msg["tool_calls"] = tool_calls
                out.append(msg)
            else:
                out.append(m)
        return out
```

adapter 在调用前过一遍 `self.adapter.normalize_messages(messages)`。

**为什么暂不加**：
- AgentLoopRunner 已正确处理 in-loop 消息
- ContextManager 已过滤 history 形态
- 历史 assistant 内容始终是 plain text（chatStore 当前实现）
- 加 ~150 行代码 + 18 个新单测，性价比低

## 相关文件

- `jarvis/api/chat.py` — ChatRequest Pydantic 定义（line 16-28）
- `jarvis/core/chat_engine.py` — 调 context_manager + runner
- `jarvis/core/context_manager.py` — `_normalize_history` (PR4) / `_sanitize_history` alias
- `jarvis/core/agent_loop.py` — `_build_assistant_turn` / `_append_tool_result`
- `jarvis/core/tool_registry.py` — `build_anthropic_tools` / `build_openai_tools`
- `jarvis/services/ai/providers/*.py` — 各 adapter
