# 贾维斯系统设计模式分析

## 1. 核心设计模式选择

### 1.1 架构风格：事件驱动 + 微内核

```
┌──────────────────────────────────────────────────────────────┐
│                      Event Bus (事件总线)                     │
│   ─────────────────────────────────────────────────────────   │
│   voice.event | camera.event | chat.event | task.event        │
└──────────────────────────────────────────────────────────────┘
         │                │                │                │
         ▼                ▼                ▼                ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ VoiceEngine │   │ SubModelProc│   │ ChatEngine  │   │ TaskEngine │
│  语音引擎   │   │ 多模态处理 │   │  对话引擎   │   │  任务引擎  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
         │                │                │                │
         └────────────────┴────────────────┴────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    Ollama / MCP 插件    │
                    │    AI 能力抽象层         │
                    └─────────────────────────┘
```

---

## 2. 详细设计模式

### 2.1 Mediator Pattern（中介者模式）

**用途**：协调各引擎之间的交互，解耦核心模块

```python
# jarvis/core/mediator.py
class JarvisMediator:
    """中介者：统一协调各引擎之间的通信"""

    def __init__(self):
        self.voice_engine: VoiceEngine = None
        self.chat_engine: ChatEngine = None
        self.task_engine: TaskEngine = None
        self.hardware_bridge: HardwareBridge = None
        self.memory_store: MemoryStore = None

    async def route_event(self, event: "JarvisEvent"):
        """根据事件类型路由到对应处理器"""
        handlers = {
            "voice.input": self.handle_voice_input,
            "camera.frame": self.handle_camera_frame,
            "chat.message": self.handle_chat_message,
            "task.execute": self.handle_task_execution,
        }
        handler = handlers.get(event.type)
        if handler:
            await handler(event)

    async def handle_voice_input(self, event: "JarvisEvent"):
        # 语音输入 → STT → 对话引擎
        text = await self.voice_engine.transcribe(event.audio_data)
        context = await self.memory_store.retrieve(text)
        response = await self.chat_engine.chat(text, context)
        await self.voice_engine.speak(response)
```

---

### 2.2 Pipeline Pattern（管道模式）

**用途**：语音/视频流的连续处理（降噪 → STT → 语义理解）

```python
# jarvis/core/pipeline.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class PipelineStage(ABC):
    @abstractmethod
    async def process(self, data: any) -> any:
        pass

class AudioPipeline:
    """音频处理管道"""

    def __init__(self):
        self.stages: list[PipelineStage] = []

    def add_stage(self, stage: PipelineStage):
        self.stages.append(stage)
        return self  # 支持链式调用

    async def execute(self, audio_data: bytes) -> str:
        data = audio_data
        for stage in self.stages:
            data = await stage.process(data)
        return data

# 使用示例
pipeline = AudioPipeline()
pipeline.add_stage(NoiseReductionStage()) \
         .add_stage(VoiceActivityDetectionStage()) \
         .add_stage(SpeechToTextStage())

result = await pipeline.execute(audio_data)
```

---

### 2.3 Repository Pattern（仓储模式）

**用途**：记忆存储的统一接口，屏蔽 SQLite/LanceDB 实现细节

```python
# jarvis/core/memory_repository.py
from abc import ABC, abstractmethod
from typing import Optional

class MemoryRepository(ABC):
    @abstractmethod
    async def save(self, key: str, value: dict, metadata: dict = None):
        pass

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        pass

    @abstractmethod
    async def delete(self, key: str):
        pass

class LanceDBMemoryRepository(MemoryRepository):
    """基于 LanceDB 的记忆仓储"""

    def __init__(self, db_path: str):
        self.client = lancedb.connect(db_path)

    async def save(self, key: str, value: dict, metadata: dict = None):
        vector = await self._embed(value["content"])
        await self.client.insert([{
            "key": key,
            "vector": vector,
            "content": value["content"],
            "metadata": metadata or {}
        }])

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        query_vec = await self._embed(query)
        results = await self.client.search(query_vec, top_k)
        return results

class SQLiteMemoryRepository(MemoryRepository):
    """基于 SQLite 的记忆仓储（结构化数据）"""

    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)

    async def save(self, key: str, value: dict, metadata: dict = None):
        # 存储结构化记忆（如用户偏好、配置）
        pass

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        # SQLite 不支持向量检索，退化为关键词搜索
        pass
```

---

### 2.4 Strategy Pattern（策略模式）

**用途**：任务执行策略的多态实现（浏览器自动化 / 桌面控制 / API 调用）

```python
# jarvis/core/task_strategy.py
from abc import ABC, abstractmethod

class TaskStrategy(ABC):
    @abstractmethod
    async def execute(self, task: "Task") -> "TaskResult":
        pass

class BrowserAutomationStrategy(TaskStrategy):
    """浏览器自动化策略"""

    async def execute(self, task: "Task") -> "TaskResult":
        # 使用 Playwright 执行浏览器任务
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            # ... 执行任务
        return TaskResult(status="success")

class DesktopControlStrategy(TaskStrategy):
    """桌面控制策略"""

    async def execute(self, task: "Task") -> "TaskResult":
        # 使用 pyautogui 执行桌面任务
        pyautogui.click(task.params["x"], task.params["y"])
        return TaskResult(status="success")

class APICallStrategy(TaskStrategy):
    """API 调用策略"""

    async def execute(self, task: "Task") -> "TaskResult":
        async with httpx.AsyncClient() as client:
            response = await client.post(task.params["url"], json=task.params["body"])
        return TaskResult(status="success", data=response.json())

class TaskExecutor:
    """任务执行器：根据任务类型选择策略"""

    def __init__(self):
        self.strategies: dict[str, TaskStrategy] = {
            "browser": BrowserAutomationStrategy(),
            "desktop": DesktopControlStrategy(),
            "api": APICallStrategy(),
        }

    async def execute(self, task: "Task") -> "TaskResult":
        strategy = self.strategies.get(task.type)
        if not strategy:
            raise ValueError(f"Unknown task type: {task.type}")
        return await strategy.execute(task)
```

---

### 2.5 Observer Pattern（观察者模式）

**用途**：硬件状态变更通知（摄像头连接/断开、麦克风音量变化）

```python
# jarvis/core/hardware_observer.py
from abc import ABC, abstractmethod
from typing import Callable

class HardwareObserver(ABC):
    @abstractmethod
    def on_event(self, event: "HardwareEvent"):
        pass

class CameraObserver(HardwareObserver):
    def on_event(self, event: "HardwareEvent"):
        if event.type == "camera.connected":
            print(f"摄像头已连接: {event.device_id}")
        elif event.type == "camera.disconnected":
            print(f"摄像头已断开: {event.device_id}")

class VoiceLevelObserver(HardwareObserver):
    def on_event(self, event: "HardwareEvent"):
        if event.type == "voice.level":
            # 更新音量指示器 UI
            pass

class HardwareMonitor:
    """硬件监控器（Subject）"""

    def __init__(self):
        self._observers: list[HardwareObserver] = []

    def attach(self, observer: HardwareObserver):
        self._observers.append(observer)

    def detach(self, observer: HardwareObserver):
        self._observers.remove(observer)

    def notify(self, event: "HardwareEvent"):
        for observer in self._observers:
            observer.on_event(event)

# 使用
monitor = HardwareMonitor()
monitor.attach(CameraObserver())
monitor.attach(VoiceLevelObserver())
monitor.notify(HardwareEvent(type="camera.connected", device_id=0))
```

---

### 2.6 Facade Pattern（外观模式）— Multimodal Sub-Model Pipeline

**用途**：封装多模态子模型（STT、Vision）的查找和调用，返回纯文本给主对话引擎

**文件**: `jarvis/services/sub_model_processor.py`

```python
# jarvis/services/sub_model_processor.py
class SubModelProcessor:
    """子模型处理器 — 多模态输入转文本, 再注入主对话引擎

    架构: 子模型 → 文本 → ChatEngine
    设计决策: 不新增独立 Router 类, 复用 AIRouter._get_client()
    """

    def __init__(self, ai_router: AIRouter):
        self.router = ai_router

    async def process_audio(self, audio_data: bytes) -> str:
        """STT: sendmeaiohyeah/whisper-large-v2 子模型 → 文本"""
        model_id = find_audio_model(Provider.OLLAMA)
        if not model_id:
            return ""
        client = self.router._get_client("ollama", model_id)
        text = await client.transcribe_audio(audio_data)
        return text.strip()

    async def process_image(self, image_data: bytes, prompt: str) -> str:
        """Vision: qwen3-vl:4b 子模型 → 文本描述"""
        return await self.router.vision_analyze(image_data, prompt)

# Mediator 集成:
class JarvisMediator:
    def __init__(self):
        self.sub_model = SubModelProcessor(self.chat_engine.router)

    async def _handle_voice_input(self, event):
        text = await self.sub_model.process_audio(audio_data)  # ← Facade
        if text:
            response = await self.chat_engine.chat(f"[语音输入] {text}")

    async def _handle_camera_frame(self, event):
        analysis = await self.sub_model.process_image(frame_data)  # ← Facade
        if analysis:
            response = await self.chat_engine.chat(f"[图片分析] {analysis}")
```

**核心价值**:
- **解耦多模态逻辑**: Mediator 不需要知道 whisper/vision 模型细节
- **复用基础设施**: 直接使用 AIRouter 的 client cache 和 failover
- **统一文本输出**: 所有子模型都返回纯文本, 格式化为 `[语音输入]`/`[图片分析]` 前缀后注入 ChatEngine
- **易于扩展**: 新增子模型类型只需在 SubModelProcessor 中添加方法

---

### 2.7 Factory Pattern（工厂模式）

**用途**：动态创建不同类型的 AI 客户端（Ollama / Claude / OpenAI）

```python
# jarvis/services/ai_client_factory.py
class AIClientFactory:
    """AI 客户端工厂"""

    @staticmethod
    def create_client(provider: str, config: dict) -> "AIClient":
        clients = {
            "ollama": OllamaClient,
            "claude": ClaudeClient,
            "openai": OpenAIClient,
        }
        client_class = clients.get(provider)
        if not client_class:
            raise ValueError(f"Unknown AI provider: {provider}")
        return client_class(**config)

# 使用
ollama = AIClientFactory.create_client("ollama", {"model": "qwen3"})
claude = AIClientFactory.create_client("claude", {"api_key": "..."})
```

---

### 2.8 Event Sourcing Pattern（事件溯源）

**用途**：记录所有对话和操作历史，支持回溯和重放

```python
# jarvis/core/event_store.py
@dataclass
class JarvisEvent:
    event_id: str
    timestamp: datetime
    event_type: str  # voice.input, chat.message, task.executed
    payload: dict
    metadata: dict

class EventStore:
    """事件存储（Event Store）"""

    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self._init_table()

    async def append(self, event: JarvisEvent):
        """追加事件"""
        await self.db.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
            (event.event_id, event.timestamp, event.event_type,
             json.dumps(event.payload), json.dumps(event.metadata))
        )

    async def get_stream(self, aggregate_id: str) -> list[JarvisEvent]:
        """获取指定聚合的所有事件"""
        cursor = await self.db.execute(
            "SELECT * FROM events WHERE metadata->>'aggregate_id' = ? ORDER BY timestamp",
            (aggregate_id,)
        )
        return [JarvisEvent(**row) for row in cursor.fetchall()]

    async def replay(self, aggregate_id: str) -> dict:
        """重放事件以重建状态"""
        events = await self.get_stream(aggregate_id)
        state = {}
        for event in events:
            state = self._apply_event(state, event)
        return state
```

---

## 3. 整体架构模式

### 3.1 Hexagonal Architecture（六边形架构）

```
                    ┌─────────────────────────┐
                    │      Driving Adapters    │
                    │  (API Routes / WebSocket │
                    │   / Hardware Bridge)     │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │      Input Ports         │
                    │  (ChatPort / VoicePort   │
                    │   / CameraPort / etc)   │
                    └───────────┬─────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐    ┌─────────────────┐    ┌───────────────┐
│  Application   │    │   Domain Core    │    │    Output     │
│    Services    │◄──►│   (Entities /    │◄──►│    Ports      │
│  (Use Cases)  │    │  Business Logic) │    │(Ollama / MCP) │
└───────────────┘    └─────────────────┘    └───────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │      Output Ports       │
                    │  (MemoryPort / DBPort  │
                    │   / FileSystemPort)    │
                    └─────────────────────────┘
```

---

## 4. 核心类图

```python
# jarvis/core/main.py

# === Domain Entities ===
@dataclass
class User:
    id: str
    name: str
    preferences: dict

@dataclass
class Conversation:
    id: str
    messages: list[Message]
    context: dict

@dataclass
class Task:
    id: str
    description: str
    steps: list[Step]
    status: TaskStatus

# === Application Services ===
class JarvisApplicationService:
    """应用服务：协调各领域对象"""

    def __init__(self, mediator: JarvisMediator):
        self.mediator = mediator

    async def process_voice(self, audio_data: bytes):
        event = JarvisEvent(type="voice.input", payload={"audio": audio_data})
        await self.mediator.route_event(event)

    async def process_message(self, text: str):
        event = JarvisEvent(type="chat.message", payload={"text": text})
        await self.mediator.route_event(event)

# === Driving Adapters ===
app = FastAPI()
ws = WebSocket()

@app.post("/api/chat")
async def chat(message: str):
    service = JarvisApplicationService(mediator)
    await service.process_message(message)

@ws.on("/ws")
async def websocket_handler(websocket: WebSocket):
    await mediator.handle_websocket(websocket)
```

---

## 5. 设计模式汇总

| 场景 | 设计模式 | 核心价值 |
|------|----------|----------|
| **引擎协调** | Mediator Pattern | 解耦引擎间直接依赖 |
| **语音处理** | Pipeline Pattern | 可组合的数据流处理 |
| **记忆存储** | Repository Pattern | 统一的数据访问接口 |
| **任务执行** | Strategy Pattern | 多态的任务执行策略 |
| **硬件状态** | Observer Pattern | 事件驱动的状态通知 |
| **AI 客户端** | Registry+Factory Pattern | 动态的客户端创建和注册 |
| **多模态子模型** | Facade Pattern | 子模型调用封装, 纯文本输出 |
| **历史记录** | Event Sourcing | 可追溯的状态变更 |
| **整体架构** | Hexagonal | 清晰的端口和适配器分离 |

---

## 6. 推荐框架组合

| 分层 | 设计模式 | 技术实现 |
|------|----------|----------|
| **表现层** | MVC / Template Method | FastAPI Routes + WebSocket |
| **应用层** | Service Layer + Mediator | JarvisApplicationService |
| **领域层** | Domain Model + Event Sourcing | Entity + EventStore |
| **基础设施** | Repository Pattern + Factory | SQLite/LanceDB + AIClientFactory |
| **通信层** | Observer / Mediator | Event Bus |

---

*设计模式的选择应基于实际需求，本方案可根据项目演进灵活调整*