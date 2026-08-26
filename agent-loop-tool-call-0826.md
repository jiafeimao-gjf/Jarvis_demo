# Agent Loop & Tool Call 优化方案（0826）

> 对照 `agent-toolcall-paradigm.md`，重新审视 JARVIS 当前的工具调用链路。
> 目标：**修三个根因 → 让 agent loop 真正能在本地 Ollama / Anthropic / MiniMax 代理 / DeepSeek 代理 上跑通完整多轮工具任务**。
>
> 范围：纯后端 + Settings UI 改动（前者主体，后者仅新增一个数字输入框）；不要求用户改任何配置。
>
> **Review 决策（0826）**：
> - ✅ `MAX_TOOL_ITERATIONS` 默认 **5 → 8**，并接入 Settings 让用户改
> - ❌ **去掉 `workspace/prompts/06-tool-loop.md`**（review 第二轮反馈："工具循环约束的提示词不需要"）。约束全部由运行时 in-message hint 承担（见 §4.3.2），不写静态 Markdown 文件
> - ✅ OpenAI / MiniMax 按两大协议（Anthropic / OpenAI）统一实现，不拆 PR3
> - ✅ Settings UI 位置：放在 **"对话行为"分类**（紧挨 TTS 开关）
> - ✅ Subagent `max_iterations` **始终跟随主对话**（删 SubagentConfig 独立字段；Orchestrator 每次对话注入 `settings.tool_loop_max_iterations`）

---

## 目录

- [0. 现状速览](#0-现状速览)
- [1. 三大问题定位与根因](#1-三大问题定位与根因)
- [2. 修复策略总览](#2-修复策略总览)
- [3. 改动文件清单](#3-改动文件清单)
- [4. 详细改动设计](#4-详细改动设计)
  - [4.1 修 `tool_id` 链路（问题 1）](#41-修-tool_id-链路问题-1)
  - [4.2 多轮 QA 工具调用上下文重放（问题 2）](#42-多轮-qa-工具调用上下文重放问题-2)
  - [4.3 Agent Loop 完备性 + 系统提示词约束（问题 3）](#43-agent-loop-完备性--系统提示词约束问题-3)
- [5. 新增 / 修改的文件逐项说明](#5-新增--修改的文件逐项说明)
- [6. 测试计划](#6-测试计划)
- [7. 风险与回滚](#7-风险与回滚)
- [8. 验收清单](#8-验收清单)

---

## 0. 现状速览

| 模块 | 文件 | 现状 |
|------|------|------|
| 工具注册 / schema | `jarvis/core/tool_registry.py` | 单一内嵌 schema，`build_anthropic_tools()` 用 `input_schema`；其他 provider 共用 |
| 工具解析 | `jarvis/core/tool_parser.py` | 本地正则解析 `[{}]` / `{...}`；返回 `ToolCall(tool, action, params, raw, id="")`，`id` 仅当 Anthropic 路径才填充 |
| 工具结果格式化 | `jarvis/core/tool_result_formatter.py` | 双形态：纯文本 `format_plain` + 结构化 Anthropic `format`（实际没被调用） |
| Agent Loop | `jarvis/core/chat_engine.py` | 三处入口 `chat` / `stream_chat` / `stream_chat_with_messages`，**非流式 `chat()` 缺 assistant turn 注入**（root cause 之一） |
| Subagent Loop | `jarvis/core/subagent.py` | `BaseSubagent.run()` 已有工具循环（BUG#18），但缺约束提示词 |
| 流式 SSE | 同上 | `stream_chat` / `stream_chat_with_messages` 正确注入 assistant turn；`chat()` 不注入 |
| 上下文管理 | `jarvis/core/context_manager.py` | `_sanitize_history` 一刀切丢弃 `tool` / `tool_result`（root cause 之二） |
| AI provider | `services/ai/providers/{ollama,anthropic,openai,minimax}.py` | Ollama/Anthropic 走 `/v1/messages`（Anthropic 格式）；OpenAI/MiniMax 走 `/v1/chat/completions`（OpenAI 格式）；目前 **MiniMax/OpenAI 完全没有 tool schema 注入** |

---

## 1. 三大问题定位与根因

### 问题 1 — 工具 `tool_id` 不对，导致请求报错

**症状**：本地 Ollama `qwen3:4b` 跑多轮工具任务时，第二次 LLM 调用大概率返回 400 或 2013（Anthropic 协议 `tool_use_id` 不匹配）。

**根因（3 处复合 bug）**：

1. **`chat()` 非流式路径漏写 assistant turn**（`chat_engine.py:272-385`）

   ```python
   for iteration_count in range(MAX_TOOL_ITERATIONS):
       response = await self.router.chat(messages, ...)
       # ... 解析 tool_calls ...
       for tool_call in tool_calls:
           # 工具执行 + result 回填到 messages
           if tool_call.id:
               messages.append({"role": "user", "content": [{
                   "type": "tool_result",
                   "tool_use_id": tool_call.id,
                   "content": result_content,
               }]})
           else:
               messages.append({"role": "user", "content": result_content})
       # ❌ 缺: messages.append({"role": "assistant", "content": [<thinking>, <text>, <tool_use>]})
   ```

   下一轮 LLM 调用拿到的 messages 形如：
   ```
   [system, user, tool_result(user), tool_result(user), ...]   ← 没有 assistant turn
   ```
   Anthropic 协议要求 `tool_result` 必须紧跟触发它的 `tool_use` assistant 消息，否则 400。

   ✅ `stream_chat`（`chat_engine.py:624`）和 `stream_chat_with_messages`（`chat_engine.py:923`）都有 `messages.append({"role": "assistant", "content": content_blocks})`，**只有 `chat()` 漏了**。

2. **`tool_call.raw` 在两处语义不一致**
   - `_extract_tool_uses`（`chat_engine.py:179`）：`raw=block.get("id", ...)`，所以 `raw == id`
   - `ToolCallParser._validate_and_create`（`tool_parser.py:99`）：`raw=raw`（整段 JSON），**id 始终为 `""`**
   - 当 LLM 走正则文本解析路径（不返回 content_blocks），`tool_call.id=""` → 走 fallback 纯文本 user 分支 → 失去结构化 ID 校验

3. **`base.py` 的 `AIResponse.content_blocks` 在 OpenAI / MiniMax 路径始终为 `None`**，意味着这两个 provider 即便支持 tool_calls（DeepSeek / GLM 都支持 OpenAI 风格 tool_calls），当前代码也检测不到 → 直接走 `ToolCallParser` 正则路径，可能解析失败。

### 问题 2 — 多轮 QA 不按约束注入工具调用信息

**症状**：用户跟 LLM 多轮对话，第 1 轮调了 `bash ls /tmp` 得到目录列表；第 2 轮问"刚才那个目录下有什么 Python 项目？"，LLM 答"我没有访问历史工具的能力"。

**根因**：`context_manager.py:270-295` 的 `_sanitize_history` 一刀切丢弃 `tool` 和 `tool_result` role：

```python
HISTORY_ALLOWED_ROLES = {"system", "user", "assistant"}
# tool/tool_result 等是工具运行期的中间表示, 无法在不丢失上下文的前提下回放
```

注释说"无法在不丢失上下文的前提下回放"——但**实际可以**：

- Anthropic /v1/messages 完全支持在历史中保留 `tool_use` 和 `tool_result` 块（只要 ID 配对）
- OpenAI /v1/chat/completions 完全支持 `tool_calls` + `role=tool` 历史回放

一刀切丢掉导致：
1. **Assistant 变 "失忆"**：之前调的工具 / 结果在历史里看不见
2. **Conversation 持久化失真**：DB 里 `messages` 有 tool/tool_result 行，重新加载后被剥离，再也回不来
3. **多轮工具任务完全无法串联**：第 N 轮的 LLM 看不见第 1..N-1 轮的工具上下文

### 问题 3 — Agent Loop 不够完备，缺约束提示词

**症状**：LLM 调完一个工具看到结果，又调一个无关的工具；同一工具调 3 次参数不变；调满 `MAX_TOOL_ITERATIONS=5` 后吐出无意义总结。

**根因（缺 4 类约束）**：

| 缺什么 | 现状 |
|--------|------|
| **Stop 信号** | 无。LLM 不知道"调满 N 次后必须给最终回答" |
| **迭代计数提示** | 无。每轮 LLM 不知道"我这是第几轮，还剩几轮" |
| **去重 / 防抖** | 无。同一 `(tool, params)` 可重复触发 |
| **终止策略** | 仅靠"无 tool_calls 就 break" + 硬上限 **5（review 后改为 8）**，未接入 Settings。LLM 不知道什么时候必须停 |

**附带的次要缺陷**：

- `chat_engine.MAX_TOOL_ITERATIONS=5`（review 后改为 **8 + 从 Settings 读**）触发后直接 break，**assistant 看不到"迭代已用完，请直接总结"的提示**，LLM 经常在不收尾的情况下被截断
- 失败工具结果直接灌进 messages，**没引导 LLM 换参数 / 换工具 / 放弃**
- 并行调用（一个 assistant turn 多个 tool_use）当前代码 `for tool_call in tool_calls` 顺序执行，**没用 `asyncio.gather`** —— 浪费延迟

---

## 2. 修复策略总览

按"问题 → 修复 → 改动的文件"三列对照：

| 问题 | 核心修复 | 涉及文件 |
|------|---------|---------|
| **#1 tool_id** | ① `chat()` 注入 assistant turn；② `_extract_tool_uses` 与 `ToolCallParser` `id` 字段统一语义；③ OpenAI / MiniMax 增加 `chat_stream_full` + `content_blocks` 规范化 | `core/chat_engine.py`、`core/tool_parser.py`、`services/ai/providers/openai.py`、`services/ai/providers/minimax.py`、`services/ai/base.py` |
| **#2 多轮注入** | `_sanitize_history` 区分协议：Anthropic 路径保留 `tool_use`/`tool_result` 块；OpenAI 路径保留 `tool_calls` + `role=tool`；回退再压缩成"工具摘要"文本 | `core/context_manager.py`、`core/entities.py` |
| **#3 完备性** | ① `ChatEngine._agent_loop` 抽出公共方法，加 stop / iteration hint / dedup / 并行执行；② `BaseSubagent.run` 同步对齐；③ 约束通过运行时 in-message hint 注入，不写静态文件 | `core/chat_engine.py`、`core/subagent.py` |

---

## 3. 改动文件清单

### 修改

| 路径 | 改动摘要 |
|------|---------|
| `jarvis/core/chat_engine.py` | ① `chat()` 补 assistant turn；② 抽出 `_run_agent_loop(messages, ..., role: "anthropic" \| "openai")` 给三处共用；③ 加 iteration hint、dedup、parallel tool exec、max-iter reached message |
| `jarvis/core/tool_parser.py` | `ToolCall.id` 改为必填字段；解析时如果 LLM 返回的 JSON 没有 `id`，生成稳定哈希 `tc-<sha1(tool+params)[:12]>`；`raw` 概念剥离（要么是 id，要么是 JSON 文本，不要混用） |
| `jarvis/core/context_manager.py` | 新增 `HISTORY_REPLAY_POLICY`：`"anthropic_blocks"`（保留 tool_use/tool_result 块） / `"openai_tool_role"`（保留 tool_calls+tool） / `"plain_summary"`（压缩成 user 文本）；按 `provider_type` 选用 |
| `jarvis/core/entities.py` | （可选）`Message.metadata` 增加 `tool_calls`、`tool_call_id` 字段，方便持久化时不丢信息；不强制，旧消息照常走 |
| `jarvis/core/subagent.py` | ① `_push_tool_result` 路径同样按 provider type 选；② run() 末尾当 `total_iterations == max_iterations` 时注入"请总结"提示；③ 增加 `seen_tool_calls` 防重复 |
| `jarvis/services/ai/base.py` | `AIResponse` 加 `provider_protocol: str = "anthropic"`（"anthropic" / "openai"）；`content_blocks` 在 OpenAI 路径下用统一结构 `[{"type": "text", "text": ...}, {"type": "tool_use", ...}]`（与 Anthropic 兼容，因为后续转换层只读 type+name+input） |
| `jarvis/services/ai/providers/openai.py` | `chat_stream_full` 按 OpenAI SSE `delta.tool_calls` 拼出 `tool_use_start` / `tool_use_delta` / `tool_use_end`；非流式 `chat` 读 `choices[0].message.tool_calls` → `content_blocks` |
| `jarvis/services/ai/providers/minimax.py` | 同 `openai.py`（MiniMax 兼容 /v1/chat/completions） |
| `jarvis/services/ai/providers/anthropic.py` | `chat_stream_full` 与 ollama 行为对齐（已基本对齐，复核 event_type 命名） |
| `jarvis/services/ai/providers/ollama.py` | 同上 |
| `tests/test_chat_engine.py` | 新增 `TestAgentLoop`：assistant turn 注入 / dedup / iteration hint / 并行 tool / max-iter reached message |
| `tests/test_tool_parser.py` | 新增 `TestToolCallIdGeneration`：缺 id 时生成稳定哈希 |
| `tests/test_context_manager.py` | 新增 `TestHistoryReplay`：anthropic / openai / plain 三种 policy |
| `tests/test_subagent.py` | 新增 `TestSubagentStopHint`：max_iter 触发后最终轮有 stop hint |
| `frontend/src/stores/settings.ts` | 新增 `tool_loop_max_iterations: number`（默认 8），纳入 settings 持久化（与现有 `tts_enabled` 字段同模式） |
| `frontend/src/components/Settings.vue` | 新增 "工具循环" section：数字输入框（min=1 max=20）+ 提示文案，绑定 `settingsStore.tool_loop_max_iterations` |
| 现有 settings API | 复用 `memory_store.get_all_settings()` / `save_setting("tool_loop_max_iterations", N)`；后端无需新接口 |

### 新增

| 路径 | 用途 |
|------|------|
| `jarvis/core/agent_loop.py` | 抽出公共 agent loop（详见 4.1） |

> 不改：API routes（`jarvis/api/*.py`）、前端 store/components、`services/ai/{registry,models,instance_config,router}.py`（仅确认 router.chat / chat_stream_full 已传 `instance`，见 BUG#17 修复）。

---

## 4. 详细改动设计

### 4.1 修 `tool_id` 链路（问题 1）

#### 4.1.1 抽 `agent_loop.py`

把 `chat_engine` 三处的工具循环提取为独立模块：

```python
# jarvis/core/agent_loop.py
"""公共 Agent Loop — chat/stream_chat/stream_chat_with_messages/subagent 共用."""

@dataclass
class AgentLoopConfig:
    max_iterations: int = 8                # review 后从 5 提到 8; 默认值在 ChatEngine._load_agent_loop_config 中由 Settings 覆盖
    provider_protocol: str = "anthropic"   # "anthropic" | "openai"
    parallel_tool_exec: bool = True        # 单 turn 多 tool_use 是否并行
    dedup_tool_calls: bool = True          # 同 (tool, params) 不重复执行
    inject_iteration_hint: bool = True     # 每轮开头注入"第 N/MAX 轮"提示
    inject_stop_hint_on_max: bool = True  # 最后一轮强制注入"请总结"


@dataclass
class ToolExecution:
    """一次工具调用的完整信息 (供 chat_engine 转 SSE 事件)."""
    tool_call: ToolCall
    result: Any
    status: str
    error: Optional[str] = None


class AgentLoopRunner:
    """统一的多轮工具循环. 支持 Anthropic / OpenAI 两种 message 格式."""

    def __init__(self, config: AgentLoopConfig, task_executor, tool_parser):
        ...

    async def run(
        self,
        messages: list[dict],
        router,
        model: str,
        instance,
        stream_first_phase: bool = True,
    ) -> AgentLoopResult:
        """跑完整 agent loop.

        Returns AgentLoopResult(
            final_response, final_thinking, tool_executions,
            iterations_used, max_iterations_reached,
        )
        """
```

**核心 loop 逻辑**（伪代码，对照 `agent-toolcall-paradigm.md` §六）：

```python
async def run(self, messages, router, ...):
    iteration = 0
    final_response = ""
    final_thinking = ""
    tool_executions = []
    last_resp_content_blocks = None

    # Phase 1: 流式首轮
    if stream_first_phase:
        async for event in router.chat_stream_full(messages, ...):
            # 透传 SSE (thinking/text/tool_use_*)
            yield event  # 由 chat_engine 进一步 yield 给前端
            # 同时本地累积
            ...

    while iteration < self.config.max_iterations:
        iteration += 1
        # 1) 检测 tool_use
        tool_uses = self._detect_tool_uses(last_resp_content_blocks, last_resp_text)
        if not tool_uses:
            break  # 无工具调用, 终止

        # 2) 注入 iteration hint (提示 LLM 还剩几轮)
        if self.config.inject_iteration_hint and iteration > 1:
            self._inject_hint(messages, iteration, self.config.max_iterations)

        # 3) 注入 assistant turn (含 tool_use 块) — 修复 chat() 的核心 bug
        assistant_turn = self._build_assistant_turn(last_resp_content_blocks, last_resp_text)
        messages.append(assistant_turn)

        # 4) 去重 + 并行执行
        unique_uses = self._dedup(tool_uses) if self.config.dedup_tool_calls else tool_uses
        exec_results = await self._exec_tools(unique_uses)  # asyncio.gather if parallel

        # 5) tool_result 注入 (按 provider_protocol 决定格式)
        for tu, exec_res in zip(unique_uses, exec_results):
            self._append_tool_result(messages, tu, exec_res)
            tool_executions.append(ToolExecution(tu, exec_res, ...))

        # 6) 末轮 stop hint
        if iteration == self.config.max_iterations and self.config.inject_stop_hint_on_max:
            self._inject_stop_hint(messages)

        # 7) 下一轮非流式 LLM 调用
        last_resp = await router.chat(messages, stream=False, ...)
        last_resp_content_blocks = last_resp.content_blocks
        last_resp_text = last_resp.content
        final_response = last_resp.content
        final_thinking = last_resp.thinking

    return AgentLoopResult(...)
```

**`_append_tool_result` 按 protocol 分发**：

```python
def _append_tool_result(self, messages, tu, exec_res):
    tool_call_id = tu["id"]
    content = ToolResultFormatter.format_plain(...)

    if self.config.provider_protocol == "anthropic":
        # Anthropic /v1/messages: user + tool_result block
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": content,
            }],
        })
    elif self.config.provider_protocol == "openai":
        # OpenAI /v1/chat/completions: role=tool
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
```

#### 4.1.2 `tool_parser.py` 统一 `id` 语义

```python
@dataclass
class ToolCall:
    tool: str
    action: str
    params: dict
    id: str                          # ← 必填, 不再默认 ""
    raw_input_json: str = ""         # ← 原 raw 字段重命名, 仅为 debug 用

    def __post_init__(self):
        # 兜底: 解析路径没拿到 id 时, 生成稳定哈希
        if not self.id:
            import hashlib
            seed = json.dumps(self.params, sort_keys=True, ensure_ascii=False)
            self.id = "tc-" + hashlib.sha1(f"{self.tool}|{seed}".encode()).hexdigest()[:12]
```

调用方：`tool_call.raw` → `tool_call.raw_input_json`（重命名后 grep 找漏改的）；`tool_call.id` 永远非空，**去掉 `if tool_call.id:` 判断分支**。

#### 4.1.3 OpenAI / MiniMax 增加 `chat_stream_full`

参考 Anthropic 实现，按 OpenAI SSE `delta.tool_calls` 逐步累积：

```python
# openai.py / minimax.py 公共片段
async def chat_stream_full(self, messages):
    payload = {... "tools": self._build_openai_tools(), "stream": True}
    current_calls: dict[int, dict] = {}  # index -> {id, name, args_partial}

    async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        async for line in resp.aiter_lines():
            if not line.startswith("data: ") or "[DONE]" in line: continue
            chunk = json.loads(line[6:])
            for choice in chunk.get("choices", []):
                d = choice.get("delta", {})
                if d.get("content"):
                    yield {"type": "text", "content": d["content"]}
                for tc_delta in d.get("tool_calls") or []:
                    idx = tc_delta.get("index", 0)
                    if idx not in current_calls:
                        # 新 tool_call 开始
                        current_calls[idx] = {
                            "id": tc_delta.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                            "name": tc_delta.get("function", {}).get("name", ""),
                            "args_parts": [],
                        }
                        yield {"type": "tool_use_start",
                               "name": current_calls[idx]["name"],
                               "id": current_calls[idx]["id"]}
                    if tc_delta.get("function", {}).get("arguments"):
                        current_calls[idx]["args_parts"].append(
                            tc_delta["function"]["arguments"]
                        )
                        yield {"type": "tool_use_delta",
                               "partial_json": tc_delta["function"]["arguments"]}

        # 收尾: parse 所有 accumulated args
        for idx, call in current_calls.items():
            try:
                args = json.loads("".join(call["args_parts"]))
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_use_end",
                   "name": call["name"],
                   "id": call["id"],
                   "input": args}
        yield {"type": "message_stop"}
```

非流式 `chat()` 同步补：`choices[0].message.tool_calls` → `content_blocks = [{"type": "tool_use", ...}]`。

#### 4.1.4 `base.py` 增加 `provider_protocol` 字段

```python
@dataclass
class AIResponse:
    content: str
    model: str
    provider: str
    provider_protocol: str = "anthropic"  # ← 新增, 方便上层分发
    ...
```

各 adapter 在 `__init__` 时把 `provider_protocol` 写死（Anthropic/Ollama → "anthropic"；OpenAI/MiniMax → "openai"）；`AIRouter._get_client_with_instance` 透传。

`chat_engine._resolve_instance` 把 protocol 也注入到 `AgentLoopConfig`：

```python
protocol = "openai" if instance and instance.type in ("openai", "minimax") else "anthropic"
loop_cfg = AgentLoopConfig(provider_protocol=protocol, ...)
runner = AgentLoopRunner(loop_cfg, self.task_executor, self.tool_parser)
```

### 4.2 多轮 QA 工具调用上下文重放（问题 2）

#### 4.2.1 `context_manager` 新增 replay policy

```python
# jarvis/core/context_manager.py

class HistoryReplayPolicy(str, Enum):
    ANTHROPIC_BLOCKS = "anthropic_blocks"   # 保留 tool_use/tool_result 块
    OPENAI_TOOL_ROLE = "openai_tool_role"   # 保留 tool_calls + role=tool
    PLAIN_SUMMARY = "plain_summary"         # 压缩为 "助手调用了 X 得到 Y" 文本


class ContextManager:
    @staticmethod
    def replay_policy_for(provider_protocol: str) -> HistoryReplayPolicy:
        return {
            "anthropic": HistoryReplayPolicy.ANTHROPIC_BLOCKS,
            "openai":    HistoryReplayPolicy.OPENAI_TOOL_ROLE,
        }.get(provider_protocol, HistoryReplayPolicy.PLAIN_SUMMARY)
```

#### 4.2.2 `_sanitize_history` 改造

替换为 `_normalize_history(history, policy)`：

| policy | 行为 |
|--------|------|
| `ANTHROPIC_BLOCKS` | 保留所有消息；`role=tool`（旧 DB）合并到下一条 user 消息的 `tool_result` 块；空 content 整条丢 |
| `OPENAI_TOOL_ROLE` | 保留所有消息；`role=tool` 转成 OpenAI `{role: tool, tool_call_id, content}`；assistant 的 `tool_use` 转 `{role: assistant, tool_calls: [...]}` |
| `PLAIN_SUMMARY` | 折叠连续 tool/tool_result + 对应 assistant turn 为单条 user "上一轮助手调了 X 工具得到 Y" |

**关键：纯文本 user 回退只在 LLM 完全没返回 content_blocks 时才使用**（问题 1 修复后这种情况应消失；保留作为防御）。

#### 4.2.3 `entities.py` 持久化字段加固

`Message.metadata` 自由 dict，目前够用；如需结构化可加：

```python
@dataclass
class ToolCallRecord:
    id: str
    tool: str
    action: str
    params: dict
    result_text: str = ""
    status: str = "success"
```

`Message` 不强制结构化（保持向后兼容），metadata 默认 `{"tool_call": ToolCallRecord.to_dict()}`。

> 备注：历史消息可能用旧字段（如 `role=tool`、content 是 JSON 字符串），`_normalize_history` 必须兼容。

#### 4.2.4 回放示例

DB 里一轮工具交互的 4 条原始记录：
```
[user: "帮我列 /tmp"]
[assistant: content="", thinking="", content_blocks=[{type:tool_use, id:toolu_abc, name:bash, input:{command:"ls /tmp"}}]]
[tool: content='{"tool":"bash",...}']           ← 旧 DB 中间表示
[tool_result: content="file1 file2 ..."]
```

经过 `_normalize_history(history, ANTHROPIC_BLOCKS)` 后：
```python
[
    {"role": "user", "content": "帮我列 /tmp"},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_abc", "name": "bash",
         "input": {"command": "ls /tmp"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_abc",
         "content": "file1 file2 ..."},
    ]},
]
```

下轮 user 问"刚才列表里有什么 Python 项目？"时，LLM 能直接看到 `tool_use_id` 关联的结果。

### 4.3 Agent Loop 完备性 + 运行时约束（问题 3）

> **约束注入方式**：review 后**不新增静态 Markdown 文件**。所有约束通过运行时动态 in-message hint 注入（§4.3.1），不污染 system prompt、不依赖 workspace 文件顺序、可随迭代计数动态调整。

#### 4.3.1 `AgentLoopRunner` 增加 hint 注入

```python
def _inject_hint(self, messages, iteration, max_iter):
    """每轮开头注入'迭代计数'提示, 让 LLM 自觉控制节奏."""
    hint = f"[系统提示] 当前工具迭代第 {iteration}/{max_iter} 轮。" \
           f"如已获得足够信息, 请直接回答用户。"
    messages.append({"role": "user", "content": hint})

def _inject_stop_hint(self, messages):
    """最后一轮强制提示停止 — 即使 LLM 还想继续."""
    messages.append({
        "role": "user",
        "content": "[系统提示] 已达最大工具迭代次数。请基于已有工具结果直接"
                  "给出最终回答，不要再调用任何工具。"
    })
```

#### 4.3.2 去重 + 并行

```python
def _dedup(self, tool_uses: list[dict]) -> list[dict]:
    """去掉 (tool, input) 完全相同的连续重复调用."""
    seen = set()
    out = []
    for tu in tool_uses:
        key = (tu["name"], json.dumps(tu.get("input", {}), sort_keys=True))
        if key in seen:
            # 注入"已跳过"提示 — 让 LLM 知道为什么没结果
            tu_id = tu.get("id", "")
            self._append_tool_result(
                self._messages, tu,
                {"status": "skipped", "message": "duplicate call, skipped"},
            )
            continue
        seen.add(key)
        out.append(tu)
    return out

async def _exec_tools(self, tool_uses: list[dict]) -> list[Any]:
    if self.config.parallel_tool_exec and len(tool_uses) > 1:
        return await asyncio.gather(
            *[self._exec_one(tu) for tu in tool_uses],
            return_exceptions=True,
        )
    return [await self._exec_one(tu) for tu in tool_uses]
```

#### 4.3.3 Subagent 同步对齐

`subagent.py` 的 `_tool_loop` 也调上述方法（抽出 `from jarvis.core.agent_loop import AgentLoopRunner`），保持行为一致；`BaseSubagent.run` 末尾加：

```python
if total_iterations == self.config.max_iterations and tool_uses:
    # 强制最后一轮拿到的响应作为 final_output
    logger.info(f"[Subagent {self.role.value}] max_iterations reached")
```

### 4.4 `MAX_TOOL_ITERATIONS` 接入 Settings（review 决策）

`MAX_TOOL_ITERATIONS` 默认值从 **5 提到 8**，并允许用户在 Settings UI 改（范围 1-20）。

#### 4.4.1 后端读取

`chat_engine.py` 启动时 + 每次 `_load_agent_loop_config()` 调：

```python
async def _load_agent_loop_config(self, instance, model) -> AgentLoopConfig:
    """从 Settings 读 max_iterations, 缺失时回退 8."""
    settings = await self.memory.get_all_settings()
    try:
        max_iter = int(settings.get("tool_loop_max_iterations", 8))
    except (TypeError, ValueError):
        max_iter = 8
    max_iter = max(1, min(20, max_iter))   # 1-20 边界保护

    protocol = self._provider_protocol(instance)   # "anthropic" | "openai"
    return AgentLoopConfig(
        max_iterations=max_iter,
        provider_protocol=protocol,
        parallel_tool_exec=True,
        dedup_tool_calls=True,
        inject_iteration_hint=True,
        inject_stop_hint_on_max=True,
    )
```

`AgentLoopRunner` 构造时传入 `config`；`MAX_TOOL_ITERATIONS` 常量保留作为兜底默认值（删掉也行，保留向后兼容旧 import）。

#### 4.4.2 前端 store + UI

`frontend/src/stores/settings.ts`：

```typescript
tool_loop_max_iterations: 8,   // 默认 8

// actions
setToolLoopMaxIterations(n: number) {
  this.tool_loop_max_iterations = Math.max(1, Math.min(20, n));
  // 复用现有 settings 持久化流程
}
```

`frontend/src/components/Settings.vue` 新增字段（紧挨 `tts_enabled` toggle，同属"对话行为"分类）：

```vue
<div class="setting-row">
  <label>工具循环最大迭代次数</label>
  <input type="number" min="1" max="20"
         v-model.number="settings.tool_loop_max_iterations"
         @change="saveSettings" />
  <p class="hint">单次对话中 LLM 最多连续调用工具的轮数。超出后强制总结并回复。范围 1-20，建议 6-10。</p>
</div>
```

> 位置：紧贴 TTS 开关下方（同 section 内的相邻 row）。

#### 4.4.3 持久化

复用现有 `memory_store.save_setting(key, value)`，无需新 API：

```
backend key: tool_loop_max_iterations
value: int (string 形式存 SQLite, 读取时 int())
前端 key: settingsStore.tool_loop_max_iterations
```

#### 4.4.4 Subagent 跟随主对话

> review 决策：**Subagent `max_iterations` 始终跟随主对话**，不再有独立字段。

实现：
1. 删除 `SubagentConfig.max_iterations` 字段（或保留但永远从 Orchestrator 注入、忽略显式传值）
2. `SubagentOrchestrator.__init__` 新增 `max_iterations` 参数（默认 8）
3. `SubagentOrchestrator.run_one / run_batch` 创建 subagent 时把 `self.max_iterations` 传给 `SubagentConfig`
4. `ChatEngine` 三处入口（chat / stream_chat / stream_chat_with_messages）每次对话注入 `self.subagent_orchestrator.max_iterations = max_iter`（与 `model` / `instance` 同一位置）

伪代码：

```python
# chat_engine.py (chat / stream_chat / stream_chat_with_messages 共同开头)
max_iter = await self._load_max_iterations()  # 从 settings 读
self.subagent_orchestrator.model = model
self.subagent_orchestrator.instance = instance
self.subagent_orchestrator.max_iterations = max_iter
```

---

## 5. 新增 / 修改的文件逐项说明

### 新增 `jarvis/core/agent_loop.py`（约 250 行）

- `AgentLoopConfig` dataclass
- `AgentLoopRunner` 类：
  - `run(messages, router, model, instance, *, stream_first_phase=True) -> AgentLoopResult`
  - `_build_assistant_turn(content_blocks, text)` — 修复问题 1 核心
  - `_append_tool_result(tool_use, exec_res)` — 按 protocol 分发
  - `_inject_hint` / `_inject_stop_hint` — 修复问题 3
  - `_dedup` / `_exec_tools` — 修复问题 3
- 暴露给 `ChatEngine` 三处入口 + `BaseSubagent` 共用

### 修改 `jarvis/core/chat_engine.py`

- `chat()`：去掉手写 loop（约 100 行 → 30 行），调 `AgentLoopRunner`
- `stream_chat()` / `stream_chat_with_messages()`：同样
- `_resolve_instance` 返回 `(instance, provider_protocol)` 元组

### 修改 `jarvis/core/tool_parser.py`

- `ToolCall.id` 必填（`__post_init__` 兜底生成稳定哈希）
- `raw` → `raw_input_json`（grep 替换 7 处）

### 修改 `jarvis/core/context_manager.py`

- 新增 `HistoryReplayPolicy` enum
- `_sanitize_history` → `_normalize_history(history, policy)`
- `build_messages` 增加 `provider_protocol` 参数

### 修改 `jarvis/core/subagent.py`

- `_tool_loop` 改为 `AgentLoopRunner.run`
- 同步 `_push_tool_result` 的 protocol 分发

### 修改 `jarvis/services/ai/base.py`

- `AIResponse.provider_protocol: str = "anthropic"`

### 修改 `services/ai/providers/{openai,minimax,anthropic,ollama}.py`

- 各 adapter `__init__` 写 `self.provider_protocol`
- openai / minimax 新增 `chat_stream_full`（参照 §4.1.3）
- 非流式 `chat` 解析 `tool_calls` → `content_blocks`

### 修改 `frontend/src/stores/settings.ts`

- 新增字段 `tool_loop_max_iterations: number`（默认 8）
- 添加 `setToolLoopMaxIterations(n)` action，含 1-20 边界保护
- 复用现有持久化机制（与 `tts_enabled` 同模式）

### 修改 `frontend/src/components/Settings.vue`

- 新增 "工具循环" section
- 数字输入框 `<input type="number" min="1" max="20" v-model.number="settings.tool_loop_max_iterations" @change="saveSettings" />`
- 提示文案："单次对话中 LLM 最多连续调用工具的轮数。超出后强制总结并回复。范围 1-20，建议 6-10。"
- 放在现有 "TTS 开关" section 附近（属于"对话行为"分类）

---

## 6. 测试计划

### 6.1 单元测试

| 测试文件 | 新增测试 | 验证目标 |
|---------|---------|---------|
| `tests/test_chat_engine.py` | `TestAgentLoop` | ① `chat()` 第二轮 LLM 调用的 messages 含 assistant turn；② 同一 (tool, params) 第二次被自动跳过；③ `MAX_TOOL_ITERATIONS` 触发后 messages 末尾含 stop hint |
| `tests/test_chat_engine.py` | `TestParallelToolExec` | 一个 assistant turn 两个 tool_use 块 → `asyncio.gather` 并行执行（mock 验证两次 execute_step 同时被调） |
| `tests/test_tool_parser.py` | `TestToolCallIdGeneration` | 解析无 id 的 JSON 时 `id` 非空且稳定（同一 params 多次解析 id 一致） |
| `tests/test_context_manager.py` | `TestHistoryReplay` | 三种 policy 各自跑一遍 fixture conversation，断言 `messages` 形态 |
| `tests/test_subagent.py` | `TestSubagentStopHint` | `max_iterations=2` + 工具永远返回成功 → 第 2 轮拿到响应即返回，不再调第 3 轮 |
| `tests/test_router_instance.py` | `TestOpenAIToolCalls` | mock OpenAI 端点返回 `tool_calls`，`chat_stream_full` 产出正确 SSE 事件链 |
| `tests/test_router_instance.py` | `TestProviderProtocol` | `AnthropicAdapter().provider_protocol == "anthropic"`, OpenAI / MiniMax 为 `"openai"` |

### 6.2 集成测试（手工，标 ✍ 待用户验收）

| 场景 | 步骤 | 预期 |
|------|------|------|
| 本地 Ollama 多轮 bash | "列 /tmp" → "刚才列出的 .log 文件里有什么" | 第 2 轮 LLM 能引用第 1 轮结果 |
| OpenAI GPT-4o 工具调用 | "查北京天气" → 用 gpt-4o 单 tool_use | 收到 tool_result 后 LLM 正常给最终回答 |
| Anthropic Claude 工具迭代 | "先读 README，再回答 X" | 两次 tool_use + 一次最终回答，无 400 错误 |
| Subagent 重复工具 | "查 5 个不同 URL，每个都调 browser" | 主对话只看到 1 次 subagent 调用，subagent 内部 5 次 browser，并行 |
| 死循环工具 | "一直 list /tmp 直到 LLM 决定停" | 达到 MAX_TOOL_ITERATIONS 后强制总结 |

### 6.3 回归测试

```bash
cd /Users/jiafei/claude/Jarvis_demo
source venv/bin/activate
python -m pytest tests/ -v          # 期望 ≥210 个测试通过 (当前 196)
./jarvis.sh restart                  # 启服
# 手工跑上面 5 个集成场景
```

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|------|------|------|
| OpenAI/MiniMax `chat_stream_full` 实现 bug，破坏现有流式 chat | 全部 OpenAI 路径 SSE 不可用 | 保留 `chat_stream` 旧实现作为 fallback；新方法失败时 router 自动回退；feature flag `AGENT_LOOP_V2`（默认 true，可在 `.env` 关闭） |
| `Message.metadata` 字段改动影响旧 conversation 加载 | 旧 DB 数据回放失败 | `_normalize_history` 严格兼容：缺字段给默认值，类型不对降级为 plain text |
| Agent Loop 公共化后某条边角 case 性能回归 | chat/stream_chat 单次延迟 +5~20ms | benchmark 已有 `time` 日志；超出 50ms 阈值告警 |
| 运行时 hint 注入影响 LLM 行为 | LLM 看到 hint 后格式/语气变化 | hint 文案简洁、保持中英文兼容；如用户反馈异常，`AgentLoopConfig.inject_iteration_hint=False` 一键关闭 |
| `MAX_TOOL_ITERATIONS=5`（默认）不够大 | 复杂任务被截断 | 默认 8；用户可在 Settings 改（新增 `tool_loop_max_iterations`，范围 1-20） |

**回滚**：`git revert <commit>` 即可；公共 loop 是新增模块，`chat()` 旧代码在 git 历史中可还原。

---

## 8. 验收清单

- [ ] `python -m pytest tests/ -v` 全绿，**新增 ≥14 个测试**
- [ ] 本地 Ollama qwen3:4b 跑通 5 个集成场景无 400 / 2013 错误
- [ ] OpenAI GPT-4o（如果有 key）能正确触发 tool_use → tool_result → 最终回答
- [ ] Anthropic Claude 3.5 Sonnet 工具迭代 2-3 轮无报错
- [ ] Subagent coder 任务"保存代码到文件"仍能完成（BUG#18 回归测试）
- [ ] `MAX_TOOL_ITERATIONS` 触发后 LLM 给出有意义的总结，不再无意义截断
- [ ] 同一 `(tool, params)` 在一个回合被自动跳过，LLM 收到 "duplicate call, skipped"
- [ ] 运行时 hint 文案经 LLM 行为抽查：iteration 提示不抢戏、stop hint 能终止调用
- [ ] CLAUDE.md "项目结构" + "Agent Loop" 章节同步更新（参考 §5 文件清单）
- [ ] `bugs.md` 新增条目 #20（本次修复）并标记 BUG#1/#2/#3 已闭合
- [ ] Settings UI 新增"工具循环最大迭代次数"输入框；用户改值后下次对话生效

---

## 9. 实施顺序（建议 PR 拆分）

> 单 PR 过大，建议分 4 个 PR 顺序合入，每个独立可回滚。

| PR | 内容 | 文件数 | 风险 |
|----|------|--------|------|
| **PR1** | `tool_parser` id 兜底 + `ToolCall.raw` 重命名 | 2 | 低，纯重构 |
| **PR2** | 新增 `agent_loop.py` + `ChatEngine.chat()` 接入 | 3 | 中，修核心 bug #1 |
| **PR3** | OpenAI/MiniMax `chat_stream_full` + Anthropic/Ollama 事件对齐 + provider_protocol 字段 | 6 | 中，影响 4 个 adapter |
| **PR4** | `ContextManager` replay policy + Subagent 对齐 + Settings UI 工具迭代次数 + `settings_store` 新字段 | 6 | 低，纯增强 |

每个 PR 后跑 `pytest tests/ -v` 全绿 + 至少 1 个端到端场景手工验证。

---

## 附录：修改前后对比示例

### 修复前（`chat()` 第 2 轮 messages）

```python
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "查 /tmp"},
    # ❌ assistant turn 缺失
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_abc", "content": "file1 file2"}]},
    # ❌ 第二轮 LLM 看到孤儿 tool_result, Anthropic 报 400 / 2013
]
```

### 修复后

```python
messages = [
    {"role": "system", "content": "...\n## 工具循环约束\n..."},
    {"role": "user", "content": "查 /tmp"},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_abc", "name": "bash",
         "input": {"command": "ls /tmp"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_abc", "content": "file1 file2"},
    ]},
    {"role": "user", "content": "[系统提示] 当前工具迭代第 2/5 轮..."},  # iteration hint
]
```

### 多轮 QA 第 3 轮 messages（修复后）

```python
# 用户问 "刚才列表里有什么 Python 项目？"
messages = [
    system,
    user("查 /tmp"),
    assistant(tool_use bash),       # ← 历史保留 (anthropic_blocks policy)
    user(tool_result file1 file2),
    user("刚才列表里有什么 Python 项目？"),  # ← 新一轮
    # LLM 此时能看到 tool_result 内容, 自然接着查 file1 内容
]
```

---

*作者：Claude · 等用户 review 后开工*
