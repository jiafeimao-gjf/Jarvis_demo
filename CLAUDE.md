# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JARVIS (贾维斯) is an intelligent assistant system with Python FastAPI backend and Vue3 frontend. It provides voice/text dialogue, vision capabilities, and task automation through Ollama LLM integration.

## Commands

### Backend (Python/FastAPI)
```bash
# Start backend (port 9529)
/Users/jiafei/claude/Jarvis_demo/venv/bin/python3 -m jarvis.main

# Or with uvicorn directly
cd /Users/jiafei/claude/Jarvis_demo && uvicorn jarvis.main:app --host 0.0.0.0 --port 9529 --reload

# Test API
curl -X POST http://localhost:9529/api/chat -H "Content-Type: application/json" -d '{"message":"你好"}'
curl -X POST http://localhost:9529/api/chat/stream -d '{"message":"你好","stream":true}'
```

### Frontend (Vue3/Vite)
```bash
cd /Users/jiafei/claude/Jarvis_demo/frontend
npm run dev      # Development server on port 8529
npm run build    # Production build
```

### Ollama (Required for LLM)
```bash
# Must be running at localhost:11434
# Models: qwen3:4b (default), qwen3-vl:4b (vision), x/z-image-turbo (image generation)
ollama list
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vue3)                       │
│   Port 8529 - Vite proxy to backend /api/* → :9529      │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│               Backend (FastAPI) - Port 9529            │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   Routes    │  │  Mediator   │  │  ChatEngine     │  │
│  │  /api/*     │──│  (Coordinator)──│  (LLM calls)    │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
│         │                │                  │           │
│         ▼                ▼                  ▼           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │ OllamaClient│  │MemoryStore  │  │VisionProcessor  │  │
│  │ (HTTP :11434│  │(SQLite/Lance│  │ (Frame analysis)│  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│            Ollama (localhost:11434)                      │
│   Models: qwen3:4b, qwen3-vl:4b, x/z-image-turbo       │
└─────────────────────────────────────────────────────────┘
```

### Key Files

- `jarvis/main.py` - FastAPI app entry, CORS middleware, WebSocket endpoint
- `jarvis/core/mediator.py` - Central coordinator (Mediator pattern), routes events to engines
- `jarvis/core/chat_engine.py` - LLM interaction, conversation context management
- `jarvis/services/ollama_client.py` - Ollama API client with `chat()` and `chat_stream()` methods
- `jarvis/api/chat.py` - `/api/chat` (non-stream) and `/api/chat/stream` (SSE) endpoints
- `frontend/src/composables/useApi.ts` - API client with SSE streaming support

### Design Patterns

- **Mediator Pattern**: `JarvisMediator` coordinates all engines (chat, voice, task, hardware)
- **Strategy Pattern**: `AIClient` abstract base, `OllamaClient` implementation
- **Factory Pattern**: `AIClientFactory` creates AI client instances
- **Observer Pattern**: `HardwareBridge` monitors hardware state changes

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api` | API info and available endpoints |
| GET | `/api/status` | System status |
| GET | `/api/health` | Health check |
| POST | `/api/chat` | Non-streaming chat (returns JSON) |
| POST | `/api/chat/stream` | Streaming chat (SSE) |
| POST | `/api/voice` | Voice processing |
| POST | `/api/camera/analyze` | Image analysis |
| WS | `/ws` | WebSocket for real-time events |

## Configuration

Environment variables in `.env` (see `.env.example`):
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=qwen3:4b`
- `PORT=9529`

## Important Notes

- Ollama must be running before backend starts
- Frontend proxies `/api` to `localhost:9529`, so CORS is configured for `localhost:8529`
- Streaming uses SSE format: `event: token\ndata: {"type": "token", "content": "..."}\n\n`
- Non-streaming `/api/chat` returns JSON directly; ensure `stream=False` when calling `ollama.chat()`