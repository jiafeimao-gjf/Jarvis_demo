# 贾维斯（JARVIS）开发计划

> 最后更新：2026-05-25

---

## 一、项目概览

| 项目 | 内容 |
|------|------|
| **项目名称** | JARVIS - 贾维斯智能助手 |
| **类型** | Web 端 AI 助手应用 |
| **核心功能** | 语音对话、视觉理解、任务自动化、个人记忆 |
| **技术栈（后端）** | Python / FastAPI / Ollama |
| **技术栈（前端）** | Vue3 / TypeScript / Tailwind CSS / Pinia |
| **设计模式** | Hexagonal / Mediator / Repository / Strategy / Observer / Pipeline |
| **代码量** | ~5,400 行 |

---

## 二、完成状态

### ✅ 全部完成

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1   │  核心功能激活          │  ✅ 完成  100%        │
│  Phase 2   │  语音交互              │  ✅ 完成  100%        │
│  Phase 3   │  视觉交互              │  ✅ 完成  100%        │
│  Phase 4   │  任务自动化            │  ✅ 完成  100%        │
│  Phase 5   │  记忆系统              │  ✅ 完成  100%        │
│  Phase 6   │  完善与优化            │  ✅ 完成  100%        │
└─────────────────────────────────────────────────────────────┘
```

### 已实现功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| **文字对话** | ✅ | POST /api/chat，对接 Ollama LLM |
| **流式响应** | ✅ | SSE 流式输出 |
| **语音识别** | ✅ | Web Speech API 前端集成 |
| **语音对话** | ✅ | POST /api/voice STT→LLM→TTS |
| **TTS 播报** | ✅ | 浏览器 SpeechSynthesis |
| **摄像头捕获** | ✅ | WebRTC getUserMedia |
| **视觉分析** | ✅ | POST /api/camera/analyze → Ollama Vision |
| **记忆存储** | ✅ | SQLite + LanceDB 双存储 |
| **任务执行** | ✅ | Strategy Pattern + LLM 任务分解 |
| **浏览器自动化** | ✅ | Playwright 策略实现 |
| **桌面控制** | ✅ | pyautogui 策略实现 |
| **主题切换** | ✅ | 深色/浅色模式 |
| **对话历史管理** | ✅ | 创建、选择、删除 |

---

## 三、最终项目结构

```
jarvis_demo/
├── README.md                    # 项目说明
├── PLAN.md                      # 架构设计文档
├── DESIGN_PATTERNS.md          # 设计模式文档
├── DEVELOPMENT_PLAN.md         # 本文件
│
├── 📄 jarvis_architecture.puml # 架构图源文件
├── 📄 design_patterns.puml      # 设计模式图源文件
│
├── 🐍 jarvis/                  # 后端 Python (23 个 .py 文件)
│   ├── main.py                # FastAPI 入口 + CORS + WebSocket
│   ├── config.py              # 配置管理 (pydantic-settings)
│   │
│   ├── api/                   # API 路由层
│   │   ├── routes.py         # 路由聚合 + /api/status + /api/health
│   │   ├── chat.py           # /api/chat + /api/chat/stream
│   │   ├── voice.py          # /api/voice + /api/voice/upload + /api/voice/tts
│   │   ├── camera.py         # /api/camera/analyze + /api/camera/ws
│   │   ├── memory.py         # /api/memory + /api/memory/{id}
│   │   └── execute.py       # /api/execute + /api/execute/step
│   │
│   ├── core/                  # 核心引擎层
│   │   ├── entities.py      # 领域实体 (Message, User, Task, Step 等)
│   │   ├── chat_engine.py   # 对话引擎 + 流式输出 + 记忆检索
│   │   ├── voice_engine.py  # Pipeline Pattern + VAD/降噪
│   │   ├── task_engine.py   # Strategy Pattern + LLM 任务分解
│   │   ├── hardware_bridge.py # Observer Pattern + 硬件状态监控
│   │   ├── memory_store.py  # Repository Pattern + SQLite/LanceDB
│   │   └── mediator.py      # Mediator Pattern + 事件路由
│   │
│   ├── services/              # 服务层
│   │   ├── ollama_client.py # Factory Pattern + LLM/Vision/T2I
│   │   └── vision_processor.py # 帧分析 + 人脸/物体检测
│   │
│   └── utils/
│       └── logger.py        # 日志工具
│
├── 🎨 frontend/               # 前端 Vue3 (16 个 .vue/.ts 文件)
│   ├── package.json         # 依赖配置 (Vue3 + Pinia + Tailwind)
│   ├── vite.config.ts       # Vite + API 代理配置
│   ├── tailwind.config.js    # Tailwind CSS 配置
│   ├── tsconfig.json        # TypeScript 配置
│   │
│   ├── index.html           # 入口 HTML
│   │
│   └── src/
│       ├── main.ts          # 应用入口
│       ├── App.vue         # 根组件
│       ├── assets/
│       │   └── main.css    # Tailwind + CSS Variables + 主题
│       │
│       ├── components/      # UI 组件
│       │   ├── Header.vue              # 顶部状态栏
│       │   ├── Sidebar.vue             # 侧边栏 + 主题切换
│       │   ├── ChatWindow.vue           # 对话窗口 + 消息发送
│       │   ├── ChatMessage.vue         # 消息气泡
│       │   ├── HardwareControls.vue    # 硬件控制按钮
│       │   └── CameraPreview.vue       # 摄像头预览
│       │
│       ├── composables/     # 组合式函数
│       │   ├── useApi.ts             # API 调用封装
│       │   └── useSpeechRecognition.ts # 语音识别 + TTS
│       │
│       ├── stores/          # 状态管理 (Pinia)
│       │   ├── chat.ts     # 对话状态
│       │   └── hardware.ts # 硬件状态
│       │
│       ├── types/
│       │   └── index.ts    # TypeScript 类型定义
│       │
│       └── lib/
│           └── utils.ts    # 工具函数 (cn, formatTime)
│
├── requirements.txt           # Python 依赖
└── memory/                  # 数据存储目录 (运行时创建)
```

---

## 四、API 端点总览

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
| WS | `/api/camera/ws` | 摄像头流 |
| GET | `/api/memory` | 记忆检索 |
| POST | `/api/memory` | 保存记忆 |
| GET | `/api/memory/{id}` | 获取记忆 |
| POST | `/api/execute` | 任务执行 |
| WS | `/ws` | 通用 WebSocket |

---

## 五、启动方式

### 后端

```bash
cd jarvis_demo

# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 或: venv\Scripts\activate  # Windows

# 2. 安装依赖
pip install -r requirements.txt

# 3. 确保 Ollama 运行
ollama serve
ollama pull qwen3       # 对话模型
ollama pull qwen3-vl     # 视觉模型

# 4. 启动后端
python -m jarvis.main
# 或
uvicorn jarvis.main:app --reload --port 8000
```

### 前端

```bash
cd frontend

# 1. 安装依赖
npm install

# 2. 启动开发服务器
npm run dev
# 访问 http://localhost:3000
```

### 生产构建

```bash
cd frontend
npm run build
# 输出到 frontend/dist/
```

---

## 六、设计模式应用

| 模式 | 模块 | 用途 |
|------|------|------|
| **Mediator** | `core/mediator.py` | 协调各引擎事件路由 |
| **Pipeline** | `core/voice_engine.py` | 音频处理链：VAD → 降噪 → STT |
| **Repository** | `core/memory_store.py` | SQLite + LanceDB 统一接口 |
| **Strategy** | `core/task_engine.py` | Browser/Desktop/API 执行策略 |
| **Observer** | `core/hardware_bridge.py` | 硬件状态变更通知 |
| **Factory** | `services/ollama_client.py` | AI 客户端动态创建 |

---

## 七、待优化项

> 以下功能已框架实现，可根据需求进一步优化

| 功能 | 当前状态 | 可优化方向 |
|------|----------|------------|
| **LanceDB 向量检索** | 依赖项可选 | 可接入专业 embedding 服务 |
| **人脸检测** | placeholder | 可集成人脸识别库 |
| **物体检测** | placeholder | 可集成 YOLO 等模型 |
| **浏览器自动化** | Playwright 基础实现 | 可扩展更多操作 |
| **移动端适配** | 基础支持 | 可优化响应式布局 |

---

*开发计划完成，项目已达到可运行状态*