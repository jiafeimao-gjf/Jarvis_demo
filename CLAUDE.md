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
| AI provider | Ollama (primary), OpenAI/Anthropic adapters config-driven |
| AI orchestration | AIRouter — model registry → adapter → API |
| Voice STT | Local openai-whisper (base model) with ffmpeg decode |
| Voice TTS | Browser SpeechSynthesis |
| Vision analysis | Ollama qwen3.5:9b via /v1/messages (Anthropic-compatible) |
| Multimodal routing | SubModelProcessor facade → sub-model → text → chat |
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

Audio and image processed by dedicated sub-models → plain text → injected into chat.

```
🎤 Audio: WebM → ffmpeg WAV → openai-whisper(base) → text → chat_engine.chat()
📷 Image: JPEG → OllamaAdapter /v1/messages (Anthropic vision) → text → frontend displays card
📋 Paste: Ctrl+V image → /camera/analyze → card in chat with fullscreen viewer
```

- **STT**: `openai-whisper` base model, lazy-loaded, `asyncio.to_thread()` non-blocking
- **Vision**: `qwen3.5:9b` via `/v1/messages` Anthropic-compatible endpoint with `content: [{image, source:...}]`
- **Camera**: 30s auto-capture with queue (max 2), start/stop toggle, frame image persisted per conversation
- **Voice**: single mic button — click to record, click to stop, timer display, no time limit
- **Image viewer**: click thumbnail → fullscreen overlay, mouse wheel zoom 50%–400%

## AI Provider System

Primary: **Ollama** (local). OpenAI/Anthropic adapters exist but are not in fallback chain.

- **Models**: `qwen3:4b` (chat), `qwen3.5:9b` (vision), `openai-whisper base` (STT)
- **OllamaAdapter**: uses `/v1/messages` (Anthropic-compatible) for all operations
- **Timeout**: httpx connect=10s, read=120s (vision per-request read=180s)
- **Configuration**: `AI__OLLAMA__*` env vars, `.env.example` reference
- **Adding a model**: add to `MODELS` in `models.py`, register adapter in `chat_engine.py`

## Tool Call Flow

1. LLM returns tool calls via `/v1/messages` response
2. `ToolCallParser` extracts `{tool, action, params}` from text
3. `ChatEngine` iterates (max 5), executes via `TaskExecutor`
4. Results formatted as **plain text** (`[工具结果] file.read: ...`) — not Anthropic tool_result blocks
5. Fed back to LLM for next reasoning cycle
6. Frontend shows tool status via SSE events

## Memory System

- Two-tier storage: SQLite for structured memory (key-value), LanceDB for vector/semantic search
- Repository pattern: `MemoryRepository` ABC → `SQLiteMemoryRepository` + `LanceDBMemoryRepository`
- Conversations are persisted to backend via `POST /api/memory/conversation/{id}` with retry logic
- Memory recall enriches system prompts with relevant context before LLM calls

## Frontend Interaction Summary

- **Chat**: Enter to send, Shift+Enter newline, Ctrl+V paste image
- **Voice**: single mic button (HardwareControls) — start/stop recording, timer, send to backend
- **Camera**: video preview + toggle start/stop auto-analysis (30s), image cards with fullscreen viewer
- **Settings**: provider/model selection, prompts, hardware config — saved to memory DB
- **Notifications**: WebSocket with exponential backoff reconnection

## Environment Variables

Copy `.env.example` to `.env`. Key vars:
- `AI__OLLAMA__*` — Ollama base URL, model, vision model, STT model, timeout
- `AI__OPENAI__API_KEY` / `AI__ANTHROPIC__API_KEY` — optional cloud providers
- `AI__DEFAULT_PROVIDER` / `AI__DEFAULT_MODEL` — active selection

## Documentation

- `DEVELOPMENT_PLAN.md` — Architecture docs, tech stack, directory structure, API design
- `DESIGN_PATTERNS.md` — Pattern rationale and implementation details
- `bugs.md` — Known bugs and their solutions
- `TODO.md` — Feature priorities and roadmap (P0/P1/P2)
