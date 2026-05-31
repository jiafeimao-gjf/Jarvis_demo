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

# Frontend build (type-check + production bundle)
cd frontend && npm run build
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI + uvicorn (port 9529) |
| Frontend framework | Vue 3 + Vite + Tailwind CSS + Pinia (port 8529) |
| Real-time | WebSocket + SSE (Server-Sent Events) |
| AI providers | Ollama (local), OpenAI, Anthropic, MiniMax |
| AI orchestration | AIRouter with automatic failover chain |
| Voice STT | Ollama sendmeaiohyeah/whisper-large-v2 (sub-model) + Browser Web Speech API |
| Voice TTS | Browser TTS (frontend SpeechSynthesis) |
| Image generation | x/z-image-turbo via Ollama (1024×1024) |
| Vision analysis | Ollama qwen3-vl:4b (sub-model pipeline) |
| Multimodal routing | SubModelProcessor — STT/Vision sub-models → text → ChatEngine |
| Memory storage | SQLite + LanceDB vector search |
| Task execution | Playwright, Claude Code MCP tools |

## Architecture Overview

```
Frontend (Vue3 :8529) ──proxy──▶ Backend (FastAPI :9529)
                                      │
                      ┌───────────────┴───────────────┐
                      │         JarvisMediator         │
                      │   (coordinates all engines)    │
                      └───┬────┬────┬────┬────┬───────┘
                          │    │    │    │    │
            ┌─────────────┤    │    │    │    └──────────┐
            ▼             ▼    ▼    ▼    ▼               ▼
      SubModelProcessor Voice Task Memory ChatEngine
      (STT + Vision      Engine Engine Store (LLM calls)
       sub-models)                                      │
            │              AI Providers                 │
            │         (Strategy + Registry)             │
            ├──────► AIRouter ──────┐                   │
            │        │              │                   │
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
│   ├── chat.py                 # /api/chat (REST) + /api/chat/stream (SSE)
│   ├── voice.py                # /api/voice (audio input)
│   ├── camera.py               # /api/camera (frame analysis, WebSocket stream)
│   ├── memory.py               # /api/memory (CRUD, conversation persistence)
│   └── execute.py              # /api/execute (task execution)
├── core/                       # Business logic engines
│   ├── mediator.py             # JarvisMediator — central coordinator (Mediator Pattern)
│   ├── entities.py             # Domain models: Message, Conversation, Task, Memory, Event
│   ├── chat_engine.py          # ChatEngine — conversation context, LLM calls, tool execution loop
│   ├── voice_engine.py         # Speech recognition & synthesis
│   ├── task_engine.py          # Task execution (Strategy Pattern: browser, system, code)
│   ├── hardware_bridge.py      # Hardware abstraction (camera, microphone)
│   ├── memory_store.py         # Memory persistence (Repository Pattern: SQLite + LanceDB)
│   ├── tool_parser.py          # Parse LLM tool call responses into structured actions
│   ├── tool_registry.py        # Central registry of available tools with schemas
│   ├── tool_result_formatter.py# Format LLM tool results for frontend display
│   └── notification.py         # Event notification system
├── services/                   # External service adapters
│   ├── sub_model_processor.py # SubModelProcessor — STT+Vision sub-model facade
│   ├── ollama_client.py        # Raw HTTP client to Ollama API (legacy)
│   ├── vision_processor.py     # Image frame analysis (legacy, subsumed by SubModelProcessor)
│   └── ai/                     # AI Provider module (Strategy + Registry Pattern)
│       ├── base.py             # AIClient ABC, AIResponse, TokenUsage
│       ├── config.py           # AI provider configuration
│       ├── models.py           # Model registry (MODELS dict: provider ↔ model_id)
│       ├── registry.py         # ProviderRegistry (factory + decorator)
│       ├── router.py           # AIRouter (auto-failover across providers)
│       ├── exceptions.py       # AI-specific errors
│       └── providers/          # Adapter implementations
│           ├── ollama.py       # OllamaAdapter (local LLM + vision)
│           ├── openai.py       # OpenAIAdapter (GPT-4o, etc.)
│           ├── anthropic.py    # AnthropicAdapter (Claude, MiniMax via proxy)
│           └── anthropic_tools.py# Anthropic-compatible tool call parsing
└── utils/
    └── logger.py               # Module-level structured logging

frontend/                       # Frontend (Vue 3 + TypeScript)
├── src/
│   ├── App.vue                 # Root component (status polling, layout orchestration)
│   ├── main.ts                 # Vue app entry
│   ├── types/index.ts          # Shared TypeScript interfaces (Message, Conversation, etc.)
│   ├── stores/                 # Pinia stores
│   │   ├── chat.ts             # Conversation state, sync from/to backend API
│   │   ├── hardware.ts         # Camera/microphone/screen status
│   │   ├── notification.ts     # Toast/notification queue
│   │   └── settings.ts         # App settings (theme, model selection, voice, provider)
│   ├── composables/
│   │   ├── useApi.ts           # API client: chat (REST+SSE), voice, camera, memory, execute
│   │   └── useSpeechRecognition.ts  # Browser Web Speech API wrapper
│   └── components/
│       ├── Header.vue          # Top nav bar with status indicators
│       ├── Sidebar.vue         # Conversation list, new chat button
│       ├── ChatWindow.vue      # Main chat UI: messages, input, streaming display
│       ├── ChatMessage.vue     # Single message bubble (markdown rendering)
│       ├── CameraPreview.vue   # Camera feed + capture + analyze UI
│       ├── HardwareControls.vue# Hardware toggle (camera, microphone, screen share)
│       ├── Settings.vue        # Settings panel (model, voice, provider, theme)
│       └── Notification.vue    # Toast/notification display
├── package.json                # Vue 3, Vite, Pinia, Tailwind, lucide-vue, marked
├── vite.config.ts              # Vite config with proxy to :9529
├── tailwind.config.js
└── tsconfig.json

tests/                          # pytest unit tests
├── test_chat_engine.py         # ChatEngine initialization, system prompt building
├── test_entities.py            # Domain entity construction
├── test_memory_store.py        # Memory CRUD operations
├── test_tool_parser.py         # Tool call parsing
└── test_tool_registry.py       # Tool registration and schema generation

DEVELOPMENT_PLAN.md             # Architecture docs, design decisions, feature roadmap
DESIGN_PATTERNS.md              # Detailed pattern documentation (Mediator, Strategy, Repository)
bugs.md                         # Known bugs and solutions
TODO.md                         # Feature priorities (P0/P1/P2)
```

## Key Design Patterns

1. **Mediator Pattern** — `JarvisMediator` in `core/mediator.py` coordinates all engines (chat, voice, task, hardware, memory, sub_model). API routes delegate to mediator; engines never call each other directly.

2. **Facade Pattern** — `SubModelProcessor` in `services/sub_model_processor.py` encapsulates STT and Vision sub-model lookup and invocation, returning plain text for injection into the main chat pipeline. This isolates multimodal complexity from the mediator.

3. **Strategy Pattern** — AI providers implement `AIClient` base class (`services/ai/base.py`). Adapters in `services/ai/providers/` implement Ollama, OpenAI, and Anthropic strategies for `chat()`, `vision_analyze()`, and `transcribe_audio()`. `TaskEngine` uses the same pattern for execution strategies.

4. **Repository Pattern** — `MemoryRepository` abstract class in `core/memory_store.py` with `SQLiteMemoryRepository` and `LanceDBMemoryRepository` implementations. Isolates persistence from business logic.

5. **Registry Pattern** — `ProviderRegistry` in `services/ai/registry.py` registers provider adapter classes and creates clients. `ToolRegistry` in `core/tool_registry.py` registers all tools with parameter schemas.

6. **Event-Driven** — `JarvisEvent` entities flow through the mediator. Frontend SSE streams deliver token-by-token responses + tool call/result lifecycle events.

## Multimodal Sub-Model Pipeline

Audio (STT) and image (Vision) are processed by dedicated Ollama sub-models, then the generated text is injected into the main chat conversation.

```
🎤 Audio Bytes ──► SubModelProcessor.process_audio()
                      │  _get_client("ollama", "sendmeaiohyeah/whisper-large-v2")
                      │  ⟩ transcribe_audio(audio_bytes)
                      ▼
                   Text ("今天天气怎么样")
                      │  [语音输入] prefix
                      ▼
                   ChatEngine.chat("[语音输入] 今天天气怎么样")
                      │
                      ▼  LLM 回复

📷 Image Bytes ──► SubModelProcessor.process_image()
                      │  AIRouter.vision_analyze(image, prompt)
                      │  ⟩ OllamaAdapter.vision_analyze() → qwen3-vl:4b
                      ▼
                   Text ("一只橙色的猫坐在窗台上...")
                      │  [图片分析] prefix
                      ▼
                   ChatEngine.chat("[图片分析] 一只橙色的猫...")
                      │
                      ▼  LLM 回复
```

- **SubModelProcessor** (`services/sub_model_processor.py`): Facade that finds audio/vision sub-models, calls them, returns text
- **Mediator integration**: `_handle_voice_input` and `_handle_camera_frame` now route through `SubModelProcessor` before `ChatEngine`
- **Frontend**: CameraPreview auto-captures frames every 5s; ChatWindow has a mic button for voice recording
- **Models**: STT uses `sendmeaiohyeah/whisper-large-v2`; Vision uses `qwen3-vl:4b`; both configurable in `OllamaConfig`
- **Fallback**: If whisper model unavailable, returns empty string and error is logged

## AI Provider System

The AI module (`services/ai/`) supports multiple providers with automatic failover:

- **Configuration** — `.env.example` shows all options (AI__OLLAMA__*, AI__ANTHROPIC__*, etc.). Default provider/model in `config.py`.
- **Model Registry** — `services/ai/models.py` defines `MODELS` dict mapping display names to `ModelInfo` (provider, capabilities, context window).
- **Client Creation** — `ProviderRegistry.create_client(model_id)` looks up model in registry, picks the right adapter class, instantiates it with connector-specific config.
- **Routing** — `AIRouter.chat()` tries primary provider; on failure iterates through `fallback_chain` (ollama → openai → anthropic → minimax).
- **Adding a new model**: add entry to `MODELS` dict in `models.py`, register adapter in `chat_engine.py` constructor with `ProviderRegistry.register()`.

## Tool Call Flow

1. LLM generates a response with `tool_use` content blocks
2. `ToolCallParser` in `core/tool_parser.py` extracts structured tool calls
3. `ChatEngine` iterates through tool calls (up to `MAX_TOOL_ITERATIONS = 5`)
4. Each tool invocation goes through `TaskExecutor` which dispatches to the right strategy
5. Results are fed back to the LLM for the next reasoning cycle
6. Frontend displays tool call/result via SSE events (`type: "tool_call"`, `type: "tool_result"`)

## Memory System

- Two-tier storage: SQLite for structured memory (key-value), LanceDB for vector/semantic search
- Repository pattern: `MemoryRepository` ABC → `SQLiteMemoryRepository` + `LanceDBMemoryRepository`
- Conversations are persisted to backend via `POST /api/memory/conversation/{id}` with retry logic
- Memory recall enriches system prompts with relevant context before LLM calls

## Frontend Data Flow

- `useApi` composable handles all HTTP/SSE communication
- SSE streaming: backend sends `data: {"type": "token", "content": "..."}\n` lines
- Frontend decodes SSE events and feeds tokens to `ChatWindow` for display
- Conversation list loads from backend on mount; synced with retry on each new message
- Settings store tracks current model, theme, voice, provider selection

## Common Tasks

- **Add a new API endpoint**: define route file in `jarvis/api/`, register in `routes.py`, implement handler using mediator
- **Add a new AI provider**: implement `AIClient` ABC in `services/ai/providers/`, register in `chat_engine.py` constructor
- **Add a new tool**: register `ToolDefinition` in `tool_registry.py` `_register_builtin_tools()`, implement execution strategy in `task_engine.py`
- **Add a new frontend component**: create in `frontend/src/components/`, import in `App.vue` or relevant parent

## Environment Variables

Copy `.env.example` to `.env` and configure. Key variables:
- `AI__OLLAMA__*` — local Ollama settings
- `AI__ANTHROPIC__API_KEY` — Claude API key (optional)
- `AI__OPENAI__API_KEY` — OpenAI API key (optional)
- `AI__DEFAULT_PROVIDER` / `AI__DEFAULT_MODEL` — active model selection

## Documentation

- `DEVELOPMENT_PLAN.md` — Architecture docs, tech stack, directory structure, API design
- `DESIGN_PATTERNS.md` — Pattern rationale and implementation details
- `bugs.md` — Known bugs and their solutions
- `TODO.md` — Feature priorities and roadmap (P0/P1/P2)
