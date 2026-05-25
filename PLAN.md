# 贾维斯（JARVIS）系统架构设计方案

## 1. 系统定位

| 维度 | 选择 |
|------|------|
| **形态** | Web 界面应用（浏览器访问） |
| **部署** | 本地运行，支持局域网访问 |
| **交互** | 语音优先 + 文字辅助 |

---

## 2. 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端框架** | FastAPI + uvicorn |
| **前端界面** | HTML/CSS/JS（单文件，无框架依赖） |
| **实时通信** | WebSocket（语音流、状态推送）+ SSE |
| **语音 STT** | 浏览器 Web Speech API / Whisper API |
| **语音 TTS** | 本地 Qwen3-TTS（mlx-audio）或浏览器 TTS |
| **本地 AI** | Ollama（LLM + Vision + T2I） |
| **记忆存储** | SQLite + 向量搜索（LanceDB） |
| **任务执行** | Claude Code MCP 工具调用 |
| **浏览器自动化** | Playwright |
| **桌面控制** | AppleScript / pyautogui |

### 硬件交互技术

| 硬件 | 前端方案 | 后端方案 |
|------|----------|----------|
| **麦克风** | Web Speech API / MediaRecorder API | PyAudio / sounddevice |
| **摄像头** | WebRTC getUserMedia / MediaDevices | OpenCV / av |
| **屏幕** | WebRTC getDisplayMedia | screencapture / Pillow |
| **扬声器** | Web Audio API | PyAudio / sounddevice |
| **键盘/鼠标** | Web APIs（有限） | pyautogui / pynput |
| **蓝牙设备** | Web Bluetooth API | bleak（BleakGATT） |
| **串口设备** | Web Serial API | pyserial |
| **传感器** | Generic Sensor API | 根据传感器类型定 |

---

## 3. 系统架构图

```
+------------------------------------------------------------------+
|                      用户浏览器 (Chrome/Safari)                   |
|  +------------+  +------------+  +------------------+               |
|  |  语音输入   |  |  文字输入  |  |   实时状态展示   |               |
|  |  (麦克风)  |  |           |  |                  |               |
|  +-----+------+  +-----+------+  +--------+---------+               |
|        |                |                  |                      |
|  +-----v----------------v------------------v----------+           |
|  |        WebRTC / MediaDevices / WebSocket           |           |
|  |  麦克风流 * 摄像头流 * 屏幕流 * 音频播放 * 事件推送 |           |
|  +----------------------------------------------------+           |
+------------------------------------------------------------+

          WebSocket              HTTP/REST              SSE
              |                     |                   |
              v                     v                   v
+------------------------------------------------------------+
|                      FastAPI 后端服务                         |
|  +----------------------------------------------------+    |
|  |                    API Routes                        |    |
|  |  POST /api/chat        - 文字对话                   |    |
|  |  POST /api/voice       - 语音识别 -> 对话          |    |
|  |  POST /api/camera      - 摄像头帧处理               |    |
|  |  WS   /ws              - WebSocket 双向通信         |    |
|  |  WS   /ws/camera       - 摄像头流式处理             |    |
|  |  WS   /ws/screen       - 屏幕共享流                 |    |
|  |  GET  /api/memory      - 记忆查询                   |    |
|  |  POST /api/execute     - 任务执行                    |    |
|  |  GET  /api/status      - 系统状态(含硬件状态)       |    |
|  +----------------------------------------------------+    |
|                                                             |
|  +----------------+  +----------------+  +----------------+  |
|  |  ChatEngine    |  |  VoiceEngine   |  |  TaskEngine    |  |
|  |  - 对话管理     |  |  - 语音处理    |  |  - 任务分解执行|  |
|  |  - 上下文       |  |  - 流式处理    |  |  - MCP工具调用 |  |
|  +-------+--------+  +-------+--------+  +-------+--------+  |
|          |                   |                    |           |
|  +-------v-------------------v--------------------v--------+  |
|  |                    Core Modules                       |    |
|  |  +----------------+  +----------------+  +-----------+ |    |
|  |  | OllamaClient   |  | MemoryStore    |  | ToolRunner| |    |
|  |  | - LLM/Vision  |  | - SQLite      |  | - MCP执行 | |    |
|  |  | - T2I         |  | - LanceDB     |  | - 自动化  | |    |
|  |  +----------------+  +----------------+  +-----------+ |    |
|  |  +----------------+  +----------------+  +-----------+ |    |
|  |  | HardwareBridge |  | VisionProcessor|  | AudioProc | |    |
|  |  | - OpenCV       |  | - 帧分析处理   |  | - 音频流  | |    |
|  |  | - PyAudio      |  | - 场景理解     |  | - 降噪    | |    |
|  |  +----------------+  +----------------+  +-----------+ |    |
|  +---------------------------------------------------------+    |
+------------------------------------------------------------+
              |                              |
              v                              v
+---------------------+        +------------------------------+
|      本地 Ollama     |        |       Claude Code / MCP      |
|  +---------------+  |        |  +------------------------+ | |
|  | qwen3         |  |        |  | 浏览器自动化(Playwright)| | |
|  | qwen3-vl      |  |        |  | 桌面控制(AppleScript)   | | |
|  | x/z-image-t   |  |        |  | 文件操作/Bash执行       | | |
|  +---------------+  |        |  +------------------------+ | |
+---------------------+        +------------------------------+
```

### 3.1 硬件数据流

```
摄像头 (Camera)  --MediaStream-->  浏览器 (前端JS)  --帧数据-->  OpenCV 处理后端
                                         |                        |
                                         | WebSocket               | 分析结果
                                         v                        v
                                  VisionProcessor  <----  Ollama (视觉AI)
                                  - 场景检测
                                  - 人脸识别
                                  - 物体识别

麦克风 (Mic)  --音频流-->  浏览器 (前端JS)  --音频数据-->  VoiceEngine
                                                           - STT
                                                           - 降噪
                                                           |
                                                           | 文字
                                                           v
                                                      Ollama (LLM)
```

---

## 4. 目录结构

```
jarvis/
    README.md
    requirements.txt
    pyproject.toml
    jarvis/
        __init__.py
        main.py              # FastAPI 入口，uvicorn 启动
        config.py            # 配置管理（环境变量）
        api/
            __init__.py
            routes.py        # API 路由定义
            chat.py          # 对话相关 API
            voice.py         # 语音相关 API
            memory.py        # 记忆相关 API
            execute.py       # 任务执行 API
            camera.py        # 摄像头相关 API
        core/
            __init__.py
            chat_engine.py   # 对话引擎（LLM 调用、上下文管理）
            voice_engine.py  # 语音引擎（STT/TTS）
            task_engine.py   # 任务执行引擎（分解 + 执行）
            memory_store.py  # 记忆存储（SQLite + LanceDB）
            hardware_bridge.py # 硬件桥接（摄像头、麦克风等）
        services/
            __init__.py
            ollama_client.py # Ollama API 封装
            tool_runner.py   # MCP 工具执行器
            browser_agent.py # 浏览器自动化代理
            vision_processor.py # 视觉处理服务
        utils/
            __init__.py
            logger.py        # 日志工具
            helpers.py       # 辅助函数
        static/
            index.html      # Web 前端单文件
memory/                  # 记忆存储目录
    jarvis.db           # SQLite 数据库
    lance_db/           # LanceDB 向量数据库
logs/                   # 日志目录
```

---

## 5. 核心模块详细设计

### 5.1 ChatEngine（对话引擎）

```python
# jarvis/core/chat_engine.py
class ChatEngine:
    def __init__(self, ollama_client, memory_store):
        self.ollama = ollama_client
        self.memory = memory_store
        self.conversation_history: list[Message] = []

    async def chat(self, user_input: str, stream: bool = True):
        # 1. 从记忆库检索相关上下文
        context = await self.memory.retrieve(user_input)
        # 2. 构建 prompt（含历史 + 记忆 + 当前输入）
        prompt = self.build_prompt(user_input, context)
        # 3. 调用 Ollama LLM
        response = await self.ollama.generate(prompt, stream=stream)
        # 4. 存储对话历史到记忆
        await self.memory.add_conversation(user_input, response)
        return response
```

### 5.2 VoiceEngine（语音引擎）

```python
# jarvis/core/voice_engine.py
class VoiceEngine:
    def __init__(self, tts_provider: str = "qwen3-tts"):
        self.tts_provider = tts_provider
        self.browser_tts = True  # 优先使用浏览器 TTS

    async def text_to_speech(self, text: str) -> bytes:
        # 返回音频数据（MP3/WAV）
        if self.browser_tts:
            # 前端处理 TTS
            return {"type": "browser_tts", "text": text}
        else:
            # 调用本地 Qwen3-TTS
            audio = await self.call_qwen3_tts(text)
            return audio

    async def process_voice_input(self, audio_data: bytes) -> str:
        # 浏览器 Web Speech API 处理 STT
        # 或调用 Whisper API
        return transcribed_text
```

### 5.3 HardwareBridge（硬件桥接）

```python
# jarvis/core/hardware_bridge.py
class HardwareBridge:
    def __init__(self):
        self.camera_stream = None
        self.mic_stream = None
        self.opencv_enabled = True

    async def start_camera(self, device_id: int = 0) -> str:
        # 启动摄像头，返回 stream_id
        pass

    async def stop_camera(self, stream_id: str):
        # 停止摄像头
        pass

    async def get_camera_frame(self, stream_id: str) -> bytes:
        # 获取单帧图像数据
        pass

    async def process_camera_stream(self, stream_id: str):
        # 持续处理摄像头流，用于实时分析
        pass

    async def start_mic(self) -> str:
        # 启动麦克风
        pass

    async def stop_mic(self):
        # 停止麦克风
        pass
```

### 5.4 VisionProcessor（视觉处理）

```python
# jarvis/services/vision_processor.py
class VisionProcessor:
    def __init__(self, ollama_client):
        self.ollama = ollama_client

    async def analyze_frame(self, frame: bytes) -> dict:
        # 分析单帧图像
        # - 场景描述
        # - 人脸检测
        # - 物体识别
        # - 文字识别（OCR）
        pass

    async def detect_faces(self, frame: bytes) -> list[dict]:
        # 人脸检测
        pass

    async def detect_objects(self, frame: bytes) -> list[dict]:
        # 物体检测
        pass

    async def stream_analysis(self, camera_stream) -> AsyncIterator[dict]:
        # 持续分析摄像头流
        async for frame in camera_stream:
            yield await self.analyze_frame(frame)
```

### 5.5 TaskEngine（任务执行引擎）

```python
# jarvis/core/task_engine.py
class TaskEngine:
    def __init__(self, tool_runner):
        self.runner = tool_runner

    async def execute_task(self, task_description: str):
        # 1. LLM 分解任务为步骤
        steps = await self.plan_steps(task_description)
        # 2. 按顺序执行每一步
        results = []
        for step in steps:
            result = await self.runner.run(step)
            results.append(result)
        # 3. 汇总结果返回
        return self.summarize(results)
```

### 5.6 MemoryStore（记忆存储）

```python
# jarvis/core/memory_store.py
class MemoryStore:
    def __init__(self, db_path: str, lance_path: str):
        self.db = sqlite3.connect(db_path)
        self.lance = lance_db.connect(lance_path)
        self._init_tables()

    async def add_conversation(self, user: str, assistant: str):
        # 存储到 SQLite
        # 同时生成向量存入 LanceDB
        vector = await self.embed(user)
        await self.lance.add(vector, {"user": user, "assistant": assistant})

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        # 向量相似度检索
        query_vec = await self.embed(query)
        results = await self.lance.search(query_vec, top_k)
        return results
```

---

## 6. API 设计

### 6.1 文字对话

```
POST /api/chat
Content-Type: application/json

Request:
{
  "message": "帮我查一下今天的天气",
  "stream": true
}

Response (SSE):
data: {"type": "status", "content": "thinking"}
data: {"type": "token", "content": "今"}
data: {"type": "token", "content": "天"}
data: {"type": "done", "content": "今天天气晴朗..."}
```

### 6.2 语音输入

```
POST /api/voice
Content-Type: multipart/form-data

Request:
  audio: <binary>

Response:
{
  "text": "帮我查一下今天的天气",
  "response": "今天天气晴朗，温度 25°C"
}
```

### 6.3 摄像头流

```
WS /ws/camera

// 客户端发送摄像头流
{"type": "start", "device_id": 0}
{"type": "frame", "data": "<base64 encoded frame>"}
{"type": "stop"}

// 服务端返回分析结果
{"type": "analysis", "result": {"scene": "室内", "faces": 1, "objects": [...]}}
{"type": "error", "message": "..."}
```

### 6.4 记忆查询

```
GET /api/memory?query=用户偏好&top_k=5

Response:
[
  {"text": "用户喜欢用中文交流", "score": 0.95},
  {"text": "用户工作日早上九点上班", "score": 0.82}
]
```

### 6.5 任务执行

```
POST /api/execute
Content-Type: application/json

Request:
{
  "task": "帮我订一张明天北京到上海的高铁票",
  "steps": [
    {"tool": "browser_open", "params": {"url": "https://12306.cn"}},
    {"tool": "browser_click", "params": {"selector": ".search-btn"}}
  ]
}

Response:
{
  "status": "success",
  "result": "已为您预订 G1234 次列车..."
}
```

---

## 7. Web 前端设计

单文件 `static/index.html`，核心功能：

| 区域 | 功能 |
|------|------|
| **顶部栏** | 系统状态、硬件连接状态（摄像头/麦克风）、设置按钮 |
| **中央对话区** | 消息气泡、语音波形动画、实时摄像头画面 |
| **底部输入区** | 文本输入框、语音按钮、发送按钮、摄像头开关 |
| **侧边栏** | 历史记录、记忆库、系统设置 |

- **语音输入**：使用 Web Speech API / MediaRecorder
- **摄像头**：WebRTC getUserMedia 捕获，Base64 编码发送给后端
- **实时响应**：SSE 流式输出
- **TTS 播放**：调用浏览器 SpeechSynthesis 或回退后端
- **屏幕共享**：WebRTC getDisplayMedia

---

## 8. 实现计划

| 阶段 | 内容 | 产出 |
|------|------|------|
| **Phase 1** | 项目骨架 + 配置 + 日志 | `jarvis/` 目录结构 |
| **Phase 2** | OllamaClient + ChatEngine | 对话功能可用 |
| **Phase 3** | MemoryStore（SQLite + LanceDB） | 记忆功能可用 |
| **Phase 4** | API 路由（chat/voice/memory/camera） | REST API 就绪 |
| **Phase 5** | HardwareBridge + VisionProcessor | 摄像头/麦克风可用 |
| **Phase 6** | Web 前端界面（含摄像头/语音） | 浏览器可访问 |
| **Phase 7** | VoiceEngine + TTS | 语音对话可用 |
| **Phase 8** | TaskEngine + ToolRunner | 任务自动化 |
| **Phase 9** | 浏览器/桌面自动化集成 | 系统自动化 |

---

## 9. 依赖

```
# requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
websockets==12.0
sse-starlette==1.8.0
httpx==0.27.0
sqlalchemy==2.0.0
lancedb==0.8.0
numpy==1.26.0
python-multipart==0.0.9
pydantic==2.8.0
opencv-python==4.10.0  # 摄像头处理
av==12.0.0            # 视频处理（OpenCV 的替代方案）
sounddevice==0.4.6    # 音频处理
pyautogui==0.9.54     # 桌面自动化
pynput==1.7.7         # 键盘鼠标控制
bleak==0.22.0         # 蓝牙设备
pyserial==3.5         # 串口设备
pillow==10.4.0        # 图像处理
```

---

## 10. 硬件能力扩展

### 10.1 多摄像头支持
- 外接 USB 摄像头
- 雷射雷达（深度摄像头）
- 红外摄像头

### 10.2 传感器集成
- 温度/湿度传感器（DHT22 via 串口）
- 光线传感器
- 运动传感器（PIR）
- 距离传感器（超声）

### 10.3 物联网控制
- 智能灯控制（MQTT）
- 继电器控制
- 电机控制

### 10.4 环境感知
- 基于摄像头的人体检测（人数统计）
- 表情识别
- 姿态估计
- 语音情感分析

---

*本方案可根据实际需求调整实现细节*