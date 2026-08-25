# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# JARVIS (贾维斯) 智能助手系统

## Project Path
`/Users/jiafei/claude/Jarvis_demo`

## Quick Start

```bash
./jarvis.sh start   # Start backend (9529) + frontend (8529)
./jarvis.sh stop    # Stop all services
./jarvis.sh status  # Check running status
```

## Development Commands

```bash
# Backend (uvicorn hot-reload)
cd /Users/jiafei/claude/Jarvis_demo
source venv/bin/activate
uvicorn jarvis.main:app --reload --host 0.0.0.0 --port 9529

# Frontend (Vite dev server)
cd frontend
npm run dev -- --port 8529

# Run all backend tests
cd /Users/jiafei/claude/Jarvis_demo
source venv/bin/activate
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_chat_engine.py -v

# Run a specific test
python -m pytest tests/test_chat_engine.py::TestChatEngineInit -v

# Run only the new modules
python -m pytest tests/test_context_manager.py tests/test_subagent.py -v

# Frontend build (type-check + production bundle)
cd frontend && npm run build
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI + uvicorn (port 9529) |
| Frontend framework | Vue 3 + Vite + Tailwind CSS + Pinia (port 8529) |
| Real-time | WebSocket + SSE (Server-Sent Events) |
| AI provider | Ollama (primary), OpenAI/Anthropic adapters config-driven |
| AI orchestration | AIRouter — model registry → adapter → API |
| Voice STT | Local Paraformer-large via funasr (MPS) with WebM direct decode |
| Voice TTS | F5-TTS voice clone (optional, default browser SpeechSynthesis fallback) |
| Vision analysis | Ollama qwen3.5:9b via /v1/messages (Anthropic-compatible) |
| Multimodal routing | SubModelProcessor facade → sub-model → text → chat |
| Context management | ContextManager — token budget + sliding window + summarization + memory injection (Strategy Pattern) |
| Subagent orchestration | SubagentOrchestrator — researcher/coder/reviewer/summarizer/planner/general, with sequential/parallel/map-reduce dispatch modes |
| Voice cloning | F5TTSBridge — wraps ../voice-clone-demo F5-TTS singleton, sentence-level PCM streaming, browser TTS graceful degradation |
| Memory storage | SQLite + LanceDB vector search |
| Task execution | Playwright, Claude Code MCP tools, SubagentStrategy |

## Architecture Overview

```
Frontend (Vue3 :8529) ──proxy──▶ Backend (FastAPI :9529)
                                      │
                      ┌───────────────┴───────────────┐
                      │         JarvisMediator         │
                      │   (coordinates all engines)    │
                      └───┬────┬────┬────┬────┬───┬───┘
                          │    │    │    │    │   │
            ┌─────────────┤    │    │    │    │   └──────────┐
            ▼             ▼    ▼    ▼    ▼               ▼
      SubModelProcessor Voice Task Memory ChatEngine  SubagentOrchestrator
      (STT + Vision      Engine Engine Store (LLM       (researcher/coder/
       sub-models)                                            reviewer/...)
            │              AI Providers                  │
            │         (Strategy + Registry)              │
            ├──────► AIRouter ──────┐                    │
            │        │              │                    │
            │   OllamaAdapter  OpenAIAdapter            │
            │   AnthropicAdapter                       │
            │   (whisper, vision, chat, tools)         │
            └──────────────────────────────────────────┘
                                                      │
               External Services                      │
               ┌──────────────────────────┐           │
               │ Ollama (localhost:11434) │◄──────────┘
               │ Playwright browser auto  │
               │ Claude Code CLI tools    │
               └──────────────────────────┘
```

## Project Structure

```
jarvis/                         # Backend (Python)
├── main.py                     # FastAPI entry (CORS, WebSocket, route registration)
├── config.py                   # Pydantic-based config (AI, hardware, storage, CORS)
├── api/                        # API route layer
│   ├── routes.py               # Route aggregation (status, health)
│   ├── chat.py                 # /api/chat (REST) + /api/chat/stream (SSE, with optional audio chunks + tts_disabled gate)
│   ├── voice.py                # /api/voice (audio input → STT → chat → TTS)
│   ├── voice_tts.py            # /api/voice/ref/* + /api/voice/synthesize + /api/voice/audio/* + /api/voice/status
│   ├── camera.py               # /api/camera (frame analysis, WebSocket stream)
│   ├── memory.py               # /api/memory (CRUD, conversation persistence)
│   ├── execute.py              # /api/execute (task execution)
│   ├── providers.py            # /api/providers (ProviderInstance CRUD)
│   └── skills.py               # /api/skills (Skill CRUD + tags/groups 全套管理, 18 端点)
├── core/                       # Business logic engines
│   ├── mediator.py             # JarvisMediator — central coordinator (Mediator Pattern)
│   ├── entities.py             # Domain models: Message, Conversation, Task, Memory, Event
│   ├── chat_engine.py          # ChatEngine — conversation context, LLM calls, tool execution loop; _build_system_prompt 注入 SkillStore 启用的 skill
│   ├── context_manager.py      # ContextManager — token budget + sliding window + summarization + memory injection (Strategy Pattern: SlidingWindow / Summarization / Hybrid)
│   ├── subagent.py             # BaseSubagent + Researcher/Coder/Reviewer/Summarizer/Planner/General + SubagentOrchestrator (sequential/parallel/map_reduce)
│   ├── voice_engine.py         # Speech recognition & synthesis
│   ├── task_engine.py          # Task execution (Strategy Pattern: file, bash, browser, desktop, api, tool, subagent)
│   ├── hardware_bridge.py      # Hardware abstraction (camera, microphone)
│   ├── memory_store.py         # Memory persistence (Repository Pattern: SQLite + LanceDB)
│   ├── tool_parser.py          # Parse LLM tool call responses into structured actions
│   ├── tool_registry.py        # Central registry of available tools with schemas (includes `subagent` tool)
│   ├── tool_result_formatter.py# Format LLM tool results for frontend display
│   ├── notification.py         # Event notification system
│   └── topic_generator.py      # Auto-generate conversation topics
├── services/                   # External service adapters
│   ├── sub_model_processor.py # SubModelProcessor — STT+Vision sub-model facade
│   ├── skill_loader.py         # Skill loader for workspace/skills/*.md (YAML frontmatter, case-insensitive)
│   ├── skill_store.py          # SkillStore — 文件 + 元数据 DB 混合存储 (Repository Pattern), 镜像 InstanceConfigStore
│   ├── ollama_client.py        # Raw HTTP client to Ollama API (legacy)
│   ├── vision_processor.py     # Image frame analysis (legacy, subsumed by SubModelProcessor)
│   ├── tts/                     # Voice cloning module (F5-TTS, optional)
│   │   ├── f5_tts_service.py    # F5TTSBridge — wraps ../voice-clone-demo TTSService singleton (lazy load ~1.2GB)
│   │   ├── voice_ref_manager.py # Reference audio CRUD (upload/list/delete/history, ffmpeg → wav)
│   │   ├── sentence_splitter.py # Chinese/English sentence boundary detection (for stream TTS trigger)
│   │   ├── pcm_chunker.py       # PCM bytes → SSE audio_chunk event payload
│   │   └── fallback.py          # browser_tts / voice_clone dict protocol (degradation contract)
│   └── ai/                     # AI Provider module (Strategy + Registry Pattern)
│       ├── base.py             # AIClient ABC, AIResponse, TokenUsage
│       ├── config.py           # AI provider configuration
│       ├── models.py           # Model registry (MODELS dict: provider ↔ model_id)
│       ├── instance_config.py  # ProviderInstance — user-defined provider configs persisted in DB
│       ├── registry.py         # ProviderRegistry (factory + decorator)
│       ├── router.py           # AIRouter (auto-failover across providers)
│       ├── exceptions.py       # AI-specific errors
│       └── providers/          # Adapter implementations
│           ├── ollama.py       # OllamaAdapter (local LLM + vision)
│           ├── openai.py       # OpenAIAdapter (GPT-4o, etc.)
│           ├── anthropic.py    # AnthropicAdapter (Claude, MiniMax via proxy)
│           ├── minimax.py      # MiniMaxAdapter (Anthropic-compatible proxy)
│           └── anthropic_tools.py# Anthropic-compatible tool call parsing
└── utils/
    └── logger.py               # Module-level structured logging

frontend/                       # Frontend (Vue 3 + TypeScript)
├── src/
│   ├── App.vue                 # Root component (status polling, layout orchestration)
│   ├── main.ts                 # Vue app entry
│   ├── types/index.ts          # Shared TypeScript interfaces (Message, Conversation, Skill, SkillConfig, ...)
│   ├── stores/                 # Pinia stores
│   │   ├── chat.ts             # Conversation state + archivedConversations + archive/restore/delete actions; sync from/to backend API
│   │   ├── hardware.ts         # Camera/microphone/screen status
│   │   ├── notification.ts     # Toast/notification queue
│   │   ├── settings.ts         # App settings (theme, model, voice, provider, tts_enabled 全局 TTS 开关)
│   │   ├── providers.ts        # ProviderInstance management (CRUD against /api/providers)
│   │   ├── skills.ts           # Skill CRUD (mirror providers.ts, localStorage 持久化)
│   │   └── voice_clone.ts      # Voice clone state (ref audio info + TTS subsystem status)
│   ├── composables/
│   │   ├── useApi.ts           # API client: chat (REST+SSE with audio events), voice, camera, memory, execute, voice-clone, skills (16 方法)
│   │   ├── useSpeechRecognition.ts  # Browser Web Speech API wrapper
│   │   └── usePCMPlayer.ts     # Web Audio API PCM int16 stream player (for cloned voice playback)
│   └── components/
│       ├── Header.vue          # Top nav bar with status indicators
│       ├── Sidebar.vue         # Conversation list (主+归档双 section), new chat button, 归档/恢复/删除
│       ├── ChatWindow.vue      # Main chat UI: messages, input, streaming display + PCM playback + slash 命令面板 (输入 / 弹)
│       ├── ChatMessage.vue     # Single message bubble (markdown rendering); 🔈 按钮受 tts_enabled 全局开关控制
│       ├── CameraPreview.vue   # Camera feed + capture + analyze UI
│       ├── HardwareControls.vue# Hardware toggle (camera, microphone, screen share)
│       ├── ProviderManager.vue # Provider instance CRUD (multi-provider per project)
│       ├── VoiceClonePanel.vue # Voice clone Settings UI: upload/record ref audio, ref_text, test synthesis
│       ├── SkillManager.vue    # Skill 管理 UI (3 Tab: 列表/标签/分组 + 编辑 modal markdown 预览 + active groups 切换)
│       ├── Settings.vue        # Settings panel: 左右布局 (sidebar 菜单 + 主内容), sticky 保存按钮
│       └── Notification.vue    # Toast/notification display
├── stores/voice_clone.ts       # Pinia store: ref audio state + TTS subsystem status
├── package.json                # Vue 3, Vite, Pinia, Tailwind, lucide-vue, marked
├── vite.config.ts              # Vite config with proxy to :9529
├── tailwind.config.js
└── tsconfig.json

tests/                          # pytest unit tests
├── test_chat_engine.py         # ChatEngine initialization, system prompt building
├── test_context_manager.py     # ContextManager — token counting, sliding window, summarization, memory injection
├── test_subagent.py            # BaseSubagent + SubagentOrchestrator + SubagentStrategy tool dispatch
├── test_entities.py            # Domain entity construction
├── test_memory_store.py        # Memory CRUD operations
├── test_tool_parser.py         # Tool call parsing
├── test_tool_registry.py       # Tool registration and schema generation
├── test_instance_config.py     # ProviderInstance lifecycle
├── test_router_instance.py     # AIRouter with ProviderInstance
└── test_skill_store.py         # SkillStore CRUD + seed + filter + tags/groups + refresh (36 用例)
```

DEVELOPMENT_PLAN.md             # Architecture docs, design decisions, feature roadmap
DESIGN_PATTERNS.md              # Detailed pattern documentation (Mediator, Strategy, Repository)
bugs.md                         # Known bugs and solutions
TODO.md                         # Feature priorities (P0/P1/P2)
```

## Key Design Patterns

1. **Mediator Pattern** — `JarvisMediator` in `core/mediator.py` coordinates all engines (chat, voice, task, hardware, memory, sub_model). API routes delegate to mediator; engines never call each other directly.

2. **Facade Pattern** — `SubModelProcessor` in `services/sub_model_processor.py` encapsulates STT and Vision sub-model lookup and invocation, returning plain text for injection into the main chat pipeline. This isolates multimodal complexity from the mediator.

3. **Strategy Pattern** — AI providers implement `AIClient` base class (`services/ai/base.py`). Adapters in `services/ai/providers/` implement Ollama, OpenAI, and Anthropic strategies for `chat()`, `vision_analyze()`, and `transcribe_audio()`. `TaskEngine` uses the same pattern for execution strategies. **ContextManager** uses Strategy for compaction (SlidingWindow / Summarization / Hybrid).

4. **Repository Pattern** — `MemoryRepository` abstract class in `core/memory_store.py` with `SQLiteMemoryRepository` and `LanceDBMemoryRepository` implementations. Isolates persistence from business logic.

5. **Registry Pattern** — `ProviderRegistry` in `services/ai/registry.py` registers provider adapter classes and creates clients. `ToolRegistry` in `core/tool_registry.py` registers all tools with parameter schemas (including the `subagent` tool).

6. **Event-Driven** — `JarvisEvent` entities flow through the mediator. Frontend SSE streams deliver token-by-token responses + tool call/result lifecycle events.

## Context Management (新增模块)

`jarvis/core/context_manager.py` — token 预算 + 滑动窗口 + 摘要 + 记忆注入的可插拔策略。

**为什么需要它**: 原来的 `ChatEngine` 在 `chat()` / `stream_chat()` / `stream_chat_with_messages()` 三处都硬编码 `get_history(limit=10)`，没有 token 预算、没有对话压缩、长对话下早期消息永久丢失。

**当前架构**:
```
┌──────────────────────────────────────────────────┐
│ ChatEngine.chat()                                │
│   ↓                                              │
│ ContextManager.build_messages(                   │
│   system_prompt, history, current_user_input,    │
│   memory_retriever=self.memory.retrieve,         │
│   model_id=model,                                │
│ )                                                │
│   ↓                                              │
│   1) 检索相关记忆 → 注入到 system_prompt 末尾      │
│   2) CompactionStrategy.compact(history, budget)  │
│      - SlidingWindowStrategy  按 token 裁剪尾部   │
│      - SummarizationStrategy 早期 LLM 摘要 + 尾部 │
│      - HybridStrategy (default)                  │
│   3) 拼成 [{system, history..., user}, ...]       │
│   返回 {messages, stats}                         │
└──────────────────────────────────────────────────┘
```

**Token 预算**: `ContextBudget` 从 `MODELS[model_id].context_window` 自动取值；找不到回退到 8192。预留 1024 给输出、800 给记忆、500 给 system。`count_tokens()` 优先用 tiktoken，回退到 4 字符/token。

**替换硬编码的方式**: 现在 `ChatEngine.chat()` 不再调用 `get_history(limit=10)`，而是把 history 列表传给 `ContextManager.build_messages()`。三种调用方式 (`chat` / `stream_chat` / `stream_chat_with_messages`) 都已迁移。

**日志输出**: 每次构建都会记录 `history_in / history_out / dropped / memory / tokens_estimate / budget_available`，方便调优。

**扩展点**: 自定义策略只需实现 `CompactionStrategy.compact(history, budget, summarizer)`，构造 `ContextManager(strategy=MyStrategy())` 即可替换默认 HybridStrategy。

## Subagent Module (新增模块)

`jarvis/core/subagent.py` — 角色化、可隔离、可并行的子代理 + 编排器。

**为什么需要它**: 原来架构只有一条主对话流 + 工具循环。复杂任务（多源调研、代码 + 复审流水线、批量生成）只能串行、上下文会被工具结果污染、无法并行。Subagent 把"子任务委派"做成一等公民。

**角色 (BaseSubagent 子类)**:
- `ResearcherSubagent` — 网络调研，结构化要点、引用来源
- `CoderSubagent` — 代码生成，先思路后代码，含边界处理
- `ReviewerSubagent` — 代码/方案复审，优/问/建三段式
- `SummarizerSubagent` — 长文摘要，结构化保留关键事实
- `PlannerSubagent` — 任务拆解，步骤 + 验收标准
- `GeneralSubagent` — 通用隔离子代理

**编排模式 (SubagentOrchestrator.run_batch)**:
- `SEQUENTIAL` — 串行，下一个任务的 context 包含前面所有输出
- `PARALLEL` — `asyncio.gather` 并行执行，独立任务
- `MAP_REDUCE` — 并行 + 可选 LLM 二次综合 (`reduce_prompt`)

**调用方式**: 主 LLM 通过 `subagent` 工具调用。工具已在 `ToolRegistry` 注册，`TaskExecutor.register_subagent(orchestrator)` 完成接线。LLM 传 `{"role": "researcher", "task": "..."}` 即可单任务调用；批量传 `{"mode": "parallel", "tasks": [...]}`。

**集成位置**:
- `ChatEngine.__init__` 创建 `SubagentOrchestrator` 并注入 `TaskExecutor`
- `SubagentStrategy` (task_engine.py) 解析 LLM 的 `subagent` 工具调用参数
- `task_engine.py` 的 `TaskExecutor.register_subagent()` 完成运行时绑定

## Voice Clone Module (新增模块)

`jarvis/services/tts/` — 基于 F5-TTS 的本地声音克隆，可选启用，未装时自动降级到浏览器 TTS。

**为什么需要它**: 默认 TTS 是浏览器 `SpeechSynthesis`，嗓音是系统默认（macOS Samantha / Microsoft Huihui）。用 F5-TTS 克隆用户声音后，LLM 回复都用用户自己的音色朗读，体验更一致。

**架构**:
```
┌─────────────────────────────────────────────────────────────┐
│ Jarivs 后端                                                  │
│                                                              │
│  jarvis/services/tts/                                       │
│  ├── F5TTSBridge ──► sys.path.insert ../voice-clone-demo    │
│  │                  └► 懒加载 demo 的 TTSService (~1.2GB)   │
│  ├── VoiceRefManager     workspace/voice/refs/voice.wav     │
│  ├── sentence_splitter   中文/英文按标点切句                │
│  ├── pcm_chunker         PCM int16 → SSE audio_chunk event  │
│  └── fallback            {type: browser_tts|voice_clone}    │
│                                                              │
│  jarvis/api/voice_tts.py                                    │
│  ├── POST /voice/ref/upload       multipart 上传 ref 音频   │
│  ├── GET  /voice/ref/info         当前 ref + tts_available  │
│  ├── PUT  /voice/ref/text         设置 ref_text (必填)      │
│  ├── POST /voice/synthesize       同步合成 wav URL          │
│  ├── GET  /voice/audio/{file}     静态服务合成结果          │
│  └── GET  /voice/status           TTS 子系统状态            │
│                                                              │
│  jarvis/api/chat.py /chat/stream (enable_tts=true 时):      │
│    每收到文本 token → 累 buffer → 按标点切句                  │
│      → 调 F5TTSBridge.synthesize_to_pcm                      │
│      → SSE event: audio (每块 PCM base64)                    │
│    流结束 → SSE event: audio_done                             │
│    F5-TTS 不可用 → SSE event: tts_fallback (前端走浏览器)    │
└─────────────────────────────────────────────────────────────┘
```

**降级契约** (前后端统一):
| 后端状态 | 返回 / 事件 | 前端路由 |
|---|---|---|
| `VOICE_CLONE__ENABLED=false` | `{type: "browser_tts"}` / `tts_fallback` 事件 | `speechSynthesis.speak()` |
| 缺 ref 音频 | 同上 | 同上 |
| 未装 f5-tts | 同上 + 日志 warning | 同上 |
| F5-TTS 推理异常 | 同上 + 单句 skip | 同上 |
| 完整链路 | `{type: "voice_clone", audio_url}` / `audio_chunk` 事件 | `<audio>` / `usePCMPlayer` |

**关键设计**:
- STT 路径强制本地 (Paraformer), STT 路径不跟随 ProviderInstance
- TTS 路径**也**不跟随 ProviderInstance — 全场景默认走本地 F5-TTS
- `available` 综合判断: `enabled=True` + ref 完整 + f5-tts 包可导入 + TTSService 加载成功
- 流式 chat 的 TTS 是**逐句触发**: 句切分用 `_find_split()` (标点 + 长度阈值)
- 前端 `usePCMPlayer` 用 `nextStartTime` 排程, 不依赖 chunk 顺序, 容忍丢包
- 前端 `ChatWindow` 收到 `audio_chunk` 时 `speechSynthesis.cancel()` 避免双播放

**参考音频要求** (前端 Settings → 声音克隆):
- 5-15 秒, 单人, 干净无背景音乐/混响
- 24kHz+ (手机录音常见, 后端自动重采样到 24kHz mono int16)
- ref_text 必须**一字不差**匹配音频内容 (F5-TTS 强制)

**启用流程**:
```bash
pip install f5-tts soundfile      # 1. 装包 (默认未装, 注释在 requirements.txt)
# .env: VOICE_CLONE__ENABLED=true # 2. 开关 (默认 false)
# 重启 backend
# 3. Settings → 声音克隆 → 上传 wav + 设置 ref_text → 试合成
```

**扩展点**: 自定义 TTS backend 实现 `STTEngine` 接口（虽然命名是 STT 但语义是 synthesis），注册到 `get_stt_engine()` 工厂即可。后续可加 OpenAI TTS API、CosyVoice 等。

**全局 TTS 开关** (`frontend/src/stores/settings.ts` 的 `tts_enabled`, 默认 `true`):
- 关闭后: 聊天请求 `enable_tts=false` → 后端 `chat.py` 加 `tts_disabled = not enable_tts` 短路 → `push_token_events` / `flush_tail_events` 早 return, 不推任何 `audio` / `tts_fallback` 事件
- 前端: `ChatMessage.vue` 的 🔈 按钮 `v-if && tts_enabled` 隐藏, `speakContent()` 顶部兜底 `if (!tts_enabled) return`
- 声音克隆配置 + 试合成仍可用 (用户主动行为, 不自动触发)
- Settings UI: 声音克隆 section 顶部 iOS 风格 toggle, 关闭时显示黄色警告条

## Skill Management Module (新增模块)

`jarvis/services/skill_store.py` + `jarvis/api/skills.py` + `frontend/src/components/SkillManager.vue` — 把原 workspace/skills/ 扫描器升级为完整 CRUD 系统。

**存储模型**: 文件 + 元数据 DB 混合
- 内容: `workspace/skills/<id>/skill.md` (git 可追踪, 手工可编辑, 文件名大小写不敏感兼容 `SKILL.md`)
- 元数据: SQLite (via `memory_store.save_setting("skills_v1")` + `("skill_config_v1")`),存 `enabled` / `tags` / `groups` / `order` / `created_at` / `updated_at`

**为什么需要它**: 原 `skill_loader.load_skills()` 只读不写; 无法关闭某个 skill; 无法按场景切换技能集; 无法在 UI 中管理。

**Skill dataclass** (`jarvis/services/skill_store.py`):
```python
@dataclass
class Skill:
    id: str                    # kebab-case, 与目录名一致
    name: str
    description: str
    content: str               # markdown body (无 frontmatter)
    tags: list[str]
    groups: list[str]          # 空 list = 总是可用
    enabled: bool = True
    order: int = 0
    file_path: str
    created_at: str
    updated_at: str
    missing: bool = False      # 文件被外部删除但 DB 仍存
```

**启用过滤逻辑** (`SkillStore.get_enabled_for_active_groups()`):
```python
active = set(config.active_groups)
for s in skills:
    if not s.enabled or s.missing: continue
    if not s.groups or (set(s.groups) & active):
        yield s   # 按 order 排序
```
- `groups=[]` = 总是注入 (跨所有场景)
- `groups=[default]` = 仅当 `default` 在 active_groups 时注入

**chat_engine 集成** (`core/chat_engine.py:121-127`):
```python
skills = get_skill_store().get_enabled_for_active_groups()  # sync, 内存缓存
if skills:
    parts.append("## 可用技能\n" + "\n".join(f"- **{s.name}**: {s.description}" for s in skills))
```
- `main.py:startup_event` eager load
- 缓存: `_cached_enabled_skills` 在 create/update/delete/toggle/reorder 后失效

**API 端点** (`jarvis/api/skills.py`, 18 端点):
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | list (含 metadata) |
| GET | `/api/skills/{id}` | get full content |
| POST | `/api/skills` | create (写文件 + DB) |
| PUT | `/api/skills/{id}` | partial update |
| DELETE | `/api/skills/{id}` | remove file + DB |
| PATCH | `/api/skills/{id}/toggle` | flip enabled |
| PATCH | `/api/skills/reorder` | bulk order |
| POST | `/api/skills/refresh` | rescan disk (auto-add new, mark missing) |
| GET/PUT | `/api/skills/config*` | active_groups, known_tags, known_groups |
| GET/POST/DELETE | `/api/skills/tags*` | rename / delete tags |
| GET/POST/DELETE | `/api/skills/groups*` | rename / delete groups |

**文件 ↔ DB 一致性规则**:
- 启动时 `refresh_from_disk()`: 磁盘有 + DB 无 → 新建 DB row (默认 enabled=True, groups=["default"]); 磁盘无 + DB 有 → 标记 `missing=True` (不删除, 保留编辑历史)
- 手工 `mkdir workspace/skills/<id>/` + 写 `skill.md`: 重启自动入库; 运行中需点 🔄「从磁盘刷新」或 `POST /api/skills/refresh`

**前端 UI** (`SkillManager.vue`, 3 Tab):
- **列表**: 搜索/过滤 (tag/group/enabled), 行内 enable toggle + 标签 chips + group badges, hover 显示 编辑/归档/删除
- **标签管理**: rename / delete (影响所有 skill)
- **分组管理**: rename / delete (默认组不可删), active groups 切换 (实时影响 chat)

**复用模式**: 完全镜像 `jarvis/services/ai/instance_config.py:InstanceConfigStore` — dataclass + store class + `memory_store.save_setting` 持久化 + lazy load 单例。

**测试**: `tests/test_skill_store.py` 36 个用例 (helpers / dataclass / seed / CRUD / toggle / reorder / filter / groups+tags / refresh / singleton), 全通过。

## Slash Commands & Conversation Archive (新增模块)

前端输入框 `/` 触发 autocomplete 面板,执行内置命令或调用 skill;后端无改动。

**4 个内置命令** (`ChatWindow.vue` 的 `slashCommands` computed):
| 命令 | 行为 |
|------|------|
| `/clear` | 归档当前 conv + 创建新 conv |
| `/stop` | `abortController.abort()` 中止当前 SSE 流 |
| `/context` | 估算 token 用量 + 显示消息数/字符数/对话占用%/含 system prompt %/模型窗口 (>80% 提示 `/clear`) |
| `/{skill_id}` | 自动从 `skillsStore.enabledSkills` 生成, 把 skill 描述+content 拼到用户消息前走普通 chat 流程 |

**autocomplete 面板 UX**:
- 输入 `/` 立刻弹出 (输入框上方 absolute 定位)
- builtin (绿色 tag) + skill (蓝色 tag) 混排
- `↑↓` 切换 / `Enter` 执行 / `Esc` 关闭
- 输入空格自动锁定命令, 菜单收起
- builtin: 直接执行; skill: 插入 `/skill_name ` 让用户继续输入具体请求

**`/context` 模型窗口估算** (`estimateContextWindow(model)`):
- qwen3 / qwen2.5 / llama3 → 32K
- claude-3 / claude-3-5 → 200K
- gpt-4o / gpt-4-turbo → 128K
- gpt-3.5 → 16K
- gemini → 1M
- 默认 8K
- token 估算: 中文 3 字符/token (偏保守)

**会话归档机制** (`frontend/src/stores/chat.ts`):
- `archivedConversations` 数组 + `archivedIds: Set<string>` (localStorage `jarvis_archived_ids_v1` 持久化)
- `archiveConversation(id)`: splice from active → fire-and-forget sync (sync 失败不影响归档) → 清空内存 messages → unshift 到 archived → 写 archivedIds
- `restoreConversation(id)`: splice from archived → unshift to active → **独立 fetch messages** (不复用 selectConversation, 避免 syncToBackend await 阻塞) → 立刻切 currentConversationId
- `deleteArchived(id)`: 永久删除 (本地 + 后端)
- `loadFromBackend`: 按 archivedIds 自动分流; 对 localStorage 有但后端无的 ID 创建 placeholder, 避免用户以为归档丢失

**Sidebar 归档 section**:
- 主列表每条 conv hover 增加 📦 归档按钮 (yellow)
- 底部 "已归档 (N)" 可折叠 section, 每项可 ↺ 恢复 / 🗑 永久删除
- 底部统计改为 `N ACTIVE · M ARCHIVED`

**selectConversation fire-and-forget** 修复:
- 旧: `await syncToBackend(prevConv)` 阻塞消息加载, 归档→恢复 / 切对话可能等几秒才看到内容
- 新: `syncToBackend(prevConv).catch(() => {})` 后台跑, 消息加载始终在主流程上

## Multimodal Sub-Model Pipeline

Audio and image processed by dedicated sub-models → plain text → injected into chat.

```
🎤 Audio: WebM → Paraformer-large (funasr, MPS) → text → chat_engine.chat()
   (旧: ffmpeg WAV → openai-whisper(base) — 现已切换到 Paraformer, 中文字错率显著更低)
📷 Image: JPEG → OllamaAdapter /v1/messages (Anthropic vision) → text → frontend displays card
📋 Paste: Ctrl+V image → /camera/analyze → card in chat with fullscreen viewer
🔊 Voice clone: LLM 回复文本 → F5-TTS (clone voice) → SSE audio chunks → Web Audio API
   (降级: 未启用/缺 ref → 浏览器 SpeechSynthesis)
```

- **STT**: Paraformer-large via funasr (MPS), lazy-loaded, supports direct WebM binary input
- **Vision**: `qwen3.5:9b` via `/v1/messages` Anthropic-compatible endpoint with `content: [{image, source:...}]`
- **Camera**: 30s auto-capture with queue (max 2), start/stop toggle, frame image persisted per conversation
- **Voice in**: single mic button — click to record, click to stop, timer display, no time limit
- **Voice out (clone)**: 流式 chat 逐句触发 F5-TTS, SSE 推 PCM chunks; 同步 chat 返回 wav URL
- **Image viewer**: click thumbnail → fullscreen overlay, mouse wheel zoom 50%–400%

## AI Provider System

Primary: **Ollama** (local). OpenAI/Anthropic adapters exist but are not in fallback chain.

- **Models**: `qwen3:4b` (chat), `qwen3.5:9b` (vision), `openai-whisper base` (STT)
- **OllamaAdapter**: uses `/v1/messages` (Anthropic-compatible) for all operations
- **ProviderInstance** (`services/ai/instance_config.py`): users can define multiple provider instances with custom model names, API keys, base URLs — persisted in DB. The active instance is the one used unless `provider_id` is passed.
- **Timeout**: httpx connect=10s, read=120s (vision per-request read=180s)
- **Configuration**: `AI__OLLAMA__*` env vars, `.env.example` reference
- **Adding a model**: add to `MODELS` in `models.py`, register adapter in `chat_engine.py`

## LLM Streaming Flow

**Phase 1 (流式)**: `chat_stream_full()` 解析 Ollama `/v1/messages` SSE 事件 → thinking/text 实时流式输出到前端，同时检测 `tool_use` block。无工具时零冗余（不重复输出），有工具时 Phase 1 文本保留。

**Phase 2 (按需)**: 如有 tool_use → 执行工具 → 再次调 LLM (stream=False) → 仅流式输出增量文本。

**Subagent 流式**: 子代理的 LLM 调用默认是非流式，结果通过 `SubagentResult.output` 一次性回注主对话。如需流式，可让 BaseSubagent 子类 yield tokens。

关键文件: `ollama.py:chat_stream_full()` → `router.py:chat_stream_full()` → `chat_engine.py:stream_chat_with_messages()`

## Tool Call Flow

1. LLM 流式输出中检测 `content_block_start{type:"tool_use"}` → 收集参数
2. `ChatEngine` 迭代执行工具 (max 5), 调用 `TaskExecutor`
3. 结果格式化为 **纯文本** (`[工具结果] file.read: ...`) 回注 LLM
4. 前端通过 SSE 事件显示工具状态 (tool_call/tool_result)
5. **`subagent` 工具**: 主 LLM 委派子任务给 `SubagentOrchestrator`，结果回注主对话

## Thinking (Reasoning)

`/v1/messages` returns `thinking` content blocks (chain-of-thought).
- Streaming: `thinking_start` → `thinking` chunks → `thinking_end` SSE events
- Display: collapsible panel in ChatWindow (live) + ChatMessage (history)
- Storage: `Message.thinking` field, saved to conversation DB

## Memory System

- Two-tier storage: SQLite for structured memory (key-value), LanceDB for vector/semantic search
- Repository pattern: `MemoryRepository` ABC → `SQLiteMemoryRepository` + `LanceDBMemoryRepository`
- Conversations are persisted to backend via `POST /api/memory/conversation/{id}` with retry logic
- Memory recall is now performed by `ContextManager.build_messages()` (replacing the previous ad-hoc retrieval in ChatEngine) — related memories are injected into the system prompt, top_k=3 by default
- **Known limitation**: `LanceDBMemoryRepository.simple_embed()` uses hash-based pseudo-embeddings, not real semantic embeddings. For production, swap in a proper embedding model.

## Frontend Interaction Summary

- **Chat**: Enter to send, Shift+Enter newline, Ctrl+V paste image, **`/` 触发 slash 命令面板** (`/clear` / `/stop` / `/context` / `/{skill_id}`)
- **Voice**: single mic button (HardwareControls) — start/stop recording, timer, send to backend
- **🔈 Speaker button** on each assistant message: 朗读该消息 (受 `tts_enabled` 全局开关控制, 关闭后按钮隐藏)
- **Camera**: video preview + toggle start/stop auto-analysis (30s), image cards with fullscreen viewer
- **Settings** (左右布局 — 侧栏菜单 + 主内容): provider/model selection, prompts, hardware config — saved to memory DB
- **Sidebar 主列表**: hover 显示 ✏️ 编辑 / 📦 归档 / 🗑 删除; 底部 "已归档 (N)" 可折叠 section, 每项可 ↺ 恢复 / 🗑 永久删除
- **ProviderManager**: add/edit/delete ProviderInstances with custom model names and API keys (for proxy providers like MiniMax)
- **SkillManager** (Settings → 技能管理): 3 Tab (列表/标签/分组) + 编辑 modal (markdown 实时预览) + active groups 切换

## Environment Variables

Copy `.env.example` to `.env`. Key vars:
- `AI__OLLAMA__*` — Ollama base URL, model, vision model, STT model, timeout
- `AI__OPENAI__API_KEY` / `AI__ANTHROPIC__API_KEY` — optional cloud providers
- `AI__DEFAULT_PROVIDER` / `AI__DEFAULT_MODEL` — active selection

## Workspace & Skills System

`workspace/` directory holds user-editable configuration and skills. **Skill 的完整 CRUD 现在走 `SkillStore` (见 [Skill Management Module](#skill-management-module-新增模块) 章节), 不再只靠 `skill_loader` 扫描。**

```
workspace/
├── persona.md          ← 角色设定 (Markdown, 编辑后重启生效)
├── abilities.md        ← 能力说明
├── memory.md           ← 记忆说明
├── tools.md            ← 额外工具说明
└── skills/             ← 技能目录 (git 可追踪, SkillStore 文件来源)
    └── my-skill/
        └── skill.md    ← YAML frontmatter + 技能文档
```

### Skill Format

```yaml
---
name: my-skill
description: 一句话描述技能能力（注入 system prompt）
tags: demo, alpha          # 可选, 自动识别
---
## 详细说明
...markdown body (LLM 可读取完整文件)...
```

### System Prompt Injection

对话开始时:
1. `ChatEngine._build_system_prompt` 调 `skill_store.get_enabled_for_active_groups()`
2. 过滤: `enabled=True AND (no groups OR groups ∩ active_groups ≠ ∅) AND not missing`
3. 按 `order` 排序, 注入: `## 可用技能\n- **name**: description`
4. Workspace 文件优先级 > DB 设置 (persona.md 覆盖 DB)

### Workflow
- **新增/修改 skill**: UI (SkillManager) 编辑 → 立即写文件 + DB; 或手工创建 `workspace/skills/<name>/skill.md` → 重启生效, 或点 🔄「从磁盘刷新」/ `POST /api/skills/refresh` 实时入库
- **删除 skill**: UI 删除按钮 (物理删除文件 + DB) 或手工 `rm -rf workspace/skills/<name>/`
- **修改角色**: 编辑 `workspace/persona.md` → 重启生效
- **保存设置**: 同时写入 DB + workspace/*.md 文件

## Documentation

- `DEVELOPMENT_PLAN.md` — Architecture docs, tech stack, directory structure, API design
- `DESIGN_PATTERNS.md` — Pattern rationale and implementation details
- `bugs.md` — Known bugs and their solutions
- `TODO.md` — Feature priorities and roadmap (P0/P1/P2)
- `tests/test_context_manager.py` — ContextManager test cases (canonical usage examples)
- `tests/test_subagent.py` — Subagent test cases (canonical usage examples)

## Common Pitfalls

- **不要重新引入 `get_history(limit=10)`** — 改用 `ContextManager.build_messages()`，否则会绕过 token 预算。
- **新工具不要忘了注册 `subagent` tool 之外的 strategy** — 修改 `TaskExecutor` 时记得更新 `__init__.strategies` 字典。
- **新增 LLM 模型要双写**: 一是 `MODELS` 字典 (`services/ai/models.py`)，二是注册 ProviderAdapter (`ChatEngine.__init__`)。
- **测试时记得 mock AIRouter** — `router.chat` 和 `router.chat_stream_full` 都是异步的，用 `AsyncMock`。
- **`SubagentConfig` 必填 `system_prompt`** — 自定义配置时显式提供，否则构造失败。
- **运行中手工加 skill 文件不自动入库** — `SkillStore.refresh_from_disk()` 只在 `load()` 和 `POST /api/skills/refresh` 时跑, 重启会重新扫描; 想要实时同步改 `chat_engine._build_system_prompt` 里调 `await skill_store.refresh_from_disk()`(有 IO 开销)。
- **chat_stream 的 `enable_tts=False` 仍推 `tts_fallback`** — 后端 `chat.py` 加 `tts_disabled = not enable_tts` 短路 `push_token_events` / `flush_tail_events`, 早 return; 不要只靠前端忽略事件, 否则带宽 + 后端 CPU 都浪费。
- **归档恢复看不到内容** — `archiveConversation` 清空 `conv.messages` 省内存, 恢复必须重新 fetch; `restoreConversation` 独立 await fetch + 切 ID, **不复用 `selectConversation`**, 否则 `await syncToBackend(prevConv)` 会阻塞。