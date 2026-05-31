# 贾维斯（JARVIS）开发计划

> 最后更新：2026-05-30

---

## 一、项目概览

| 项目 | 内容 |
|------|------|
| **项目名称** | JARVIS - 贾维斯智能助手 |
| **类型** | Web 端 AI 助手应用 |
| **核心功能** | 语音对话、视觉理解、任务自动化、个人记忆 |
| **技术栈（后端）** | Python / FastAPI / Ollama / Anthropic |
| **技术栈（前端）** | Vue3 / TypeScript / Tailwind CSS / Pinia |
| **设计模式** | Hexagonal / Mediator / Facade / Repository / Strategy / Observer |
| **代码量** | ~7,000 行 |

---

## 二、架构设计

### 2.1 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端框架** | FastAPI + uvicorn |
| **前端界面** | Vue3 + Vite + Tailwind CSS |
| **实时通信** | WebSocket + SSE |
| **语音 STT** | Ollama sendmeaiohyeah/whisper-large-v2 子模型 + 浏览器 Web Speech API |
| **语音 TTS** | 浏览器 SpeechSynthesis |
| **视觉分析** | Ollama qwen3-vl:4b 子模型 → 文本 → 对话引擎 |
| **本地 AI** | Ollama（LLM + Vision + Whisper）+ Anthropic API |
| **记忆存储** | SQLite + 向量搜索（LanceDB） |
| **任务执行** | Claude Code MCP 工具调用 |

### 2.2 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vue3)                       │
│   Port 8529 - Vite proxy to backend /api/* → :9529      │
│   📸 Camera auto-capture → Vision → Chat    🎤 Mic → STT│
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│               Backend (FastAPI) - Port 9529            │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   Routes    │  │  Mediator   │  │  SubModelProc   │  │
│  │  /api/*     │──│  (Coordinator)──│  (STT + Vision)  │  │
│  └─────────────┘  └─────────────┘  └────────┬────────┘  │
│         │                │                  │           │
│         ▼                ▼                  ▼           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  AIRouter   │  │MemoryStore  │  │  ChatEngine     │  │
│  │  (failover) │  │(SQLite/Lance│  │  (LLM + tools)  │  │
│  └──────┬──────┘  └─────────────┘  └─────────────────┘  │
│         │                                                │
│         ▼                                                │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Ollama (localhost:11434)                          │   │
│  │  ├── LLM:     qwen3:4b       (chat, tools)       │   │
│  │  ├── Vision:  qwen3-vl:4b    (image → text)      │   │
│  │  ├── STT:     sendmeaiohyeah/whisper-large-v2 (audio → text)     │   │
│  │  └── Image:   x/z-image-turbo (text → image)     │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.3 目录结构

```
jarvis_demo/
├── jarvis/                  # 后端 Python
│   ├── main.py              # FastAPI 入口 + CORS + WebSocket
│   ├── config.py            # 配置管理
│   ├── api/                 # API 路由层
│   │   ├── routes.py       # 路由聚合
│   │   ├── chat.py        # /api/chat + /api/chat/stream
│   │   ├── voice.py       # 语音相关
│   │   ├── camera.py      # 摄像头相关
│   │   ├── memory.py      # 记忆相关
│   │   └── execute.py    # 任务执行
│   ├── core/               # 核心引擎层
│   │   ├── entities.py    # 领域实体
│   │   ├── chat_engine.py # 对话引擎
│   │   ├── voice_engine.py # 语音引擎 (TTS + Pipeline)
│   │   ├── task_engine.py # 任务执行引擎
│   │   ├── hardware_bridge.py # 硬件桥接
│   │   ├── memory_store.py # 记忆存储
│   │   ├── mediator.py   # 中介者模式
│   │   └── tool_parser.py # 工具解析
│   └── services/           # 服务层
│       ├── sub_model_processor.py # ★ 子模型处理器 (STT + Vision)
│       ├── skill_loader.py    # ★ 技能加载器 (workspace/skills)
│       ├── ai/             # AI Provider 模块
│       │   ├── base.py     # AIClient ABC (含 transcribe_audio)
│       │   ├── models.py   # Model registry (whisper, vision)
│       │   ├── router.py   # AIRouter — failover
│       │   └── providers/  # OllamaAdapter etc.
│
├── frontend/               # 前端 Vue3
│   ├── src/
│   │   ├── components/    # UI 组件
│   │   ├── composables/   # 组合式函数
│   │   ├── stores/       # Pinia 状态
│   │   └── types/        # TypeScript 类型
│   └── package.json
│
├── memory/                 # 数据存储 (运行时创建)
├── logs/                   # 日志目录
└── requirements.txt
```

---

## 三、已完成功能

| 功能 | 状态 | 说明 |
|------|------|------|
| **文字对话** | ✅ | POST /api/chat + /api/chat/stream |
| **流式响应** | ✅ | SSE 流式输出 + 工具调用状态 |
| **多 Provider** | ✅ | Ollama + Anthropic + MiniMax |
| **语音识别** | ✅ | Ollama sendmeaiohyeah/whisper-large-v2 子模型 + Web Speech API |
| **语音对话** | ✅ | POST /api/voice → STT → ChatEngine → TTS |
| **TTS 播报** | ✅ | 浏览器 SpeechSynthesis |
| **摄像头捕获** | ✅ | WebRTC getUserMedia + 自动帧捕获 |
| **视觉分析** | ✅ | Ollama qwen3.5:9b (Anthropic vision format /v1/messages) |
| **多模态融合** | ✅ | SubModelProcessor → [语音/图片] 文本 → ChatEngine |
| **语音输入** | ✅ | 单按钮录音, 无限时长, 实时计时, openai-whisper STT |
| **图片粘贴** | ✅ | Ctrl+V 粘贴, 自动分析, 全屏查看器 (缩放 50%-400%) |
| **摄像头自动分析** | ✅ | 30s 间隔, 启动/停止切换, 队列 (最大 2), 帧缓存去重 |
| **图片持久化** | ✅ | 按对话存储 JPEG 到磁盘, message.image 存 URL 路径 |
| **Thinking 思考链** | ✅ | /v1/messages thinking blocks → SSE 流式 → 前端折叠面板 |
| **图片路径解析** | ✅ | LLM 回复中 ![alt](path) → 后端读取 → base64 data URL |
| **System Prompt 文件化** | ✅ | workspace/prompts/*.md 文件拼接, 编辑即生效 |
| **Ollama 模型列表** | ✅ | GET /api/chat/models → Ollama /api/tags 动态加载 |
| **记忆存储** | ✅ | SQLite + LanceDB |
| **技能系统** | ✅ | workspace/skills/*/skill.md YAML frontmatter → system prompt |
| **Workspace 文件** | ✅ | persona.md 等角色设定文件, 编辑即生效 |
| **任务执行** | ✅ | Strategy Pattern (file, bash, browser, desktop, api, tool) |
| **对话历史** | ✅ | localStorage + 后端 SQLite 持久化 + 图片文件存储 |

---

## 四、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 系统状态 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/chat` | 文字对话 |
| POST | `/api/chat/stream` | 流式对话 |
| POST | `/api/voice` | 语音对话 |
| POST | `/api/voice/upload` | 上传音频 |
| POST | `/api/voice/tts` | 文字转语音 |
| POST | `/api/camera/analyze` | 图像分析 |
| WS | `/ws` | 通用 WebSocket |
| GET | `/api/memory` | 记忆检索 |
| POST | `/api/memory` | 保存记忆 |
| POST | `/api/execute` | 任务执行 |
| GET | `/api/notifications` | 通知历史 |
| GET/PUT | `/api/config` | 系统配置 |

---

## 五、设计模式应用

| 模式 | 模块 | 用途 |
|------|------|------|
| **Mediator** | `core/mediator.py` | 协调各引擎事件路由 |
| **Facade** | `services/sub_model_processor.py` | 多模态子模型查找和调用, 返回纯文本 |
| **Pipeline** | `core/voice_engine.py` | 音频处理链 (TTS) |
| **Repository** | `core/memory_store.py` | SQLite + LanceDB 统一接口 |
| **Strategy** | `core/task_engine.py`, `services/ai/` | 任务执行策略 + AI Provider 多态 |
| **Observer** | `core/hardware_bridge.py` | 硬件状态变更通知 |
| **Registry** | `services/ai/registry.py` | Provider 注册 + Factory 创建 |

详细说明见 [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md)

---

## 六、待优化项

| 功能 | 当前状态 | 可优化方向 |
|------|----------|------------|
| **LanceDB 向量检索** | 依赖项可选 | 可接入专业 embedding 服务 |
| **移动端适配** | 基础支持 | 可优化响应式布局 |
| **用户认证** | 未实现 | JWT Token |

---

## 七、快速启动

### 后端
```bash
cd /Users/jiafei/claude/Jarvis_demo
./jarvis.sh start        # 使用一键脚本
# 或手动启动
source venv/bin/activate
python -m uvicorn jarvis.main:app --host 0.0.0.0 --port 9529
```

### 前端
```bash
cd frontend
npm run dev
```

---

*开发计划完成，项目已达到可运行状态*