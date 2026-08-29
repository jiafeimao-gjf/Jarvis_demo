# Jarvis（贾维斯）智能助手系统

![Jarvis 架构图](docs/JarvisArchitecture.png)

## 系统概述

Jarvis 是基于 FastAPI + Vue 3 的智能助手系统，支持完整的多模态交互、子代理委派、工具执行和长程记忆。

**技术栈**

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Pinia + Tailwind CSS（端口 8529）|
| 后端 | FastAPI + uvicorn（端口 9529）|
| AI | Ollama（本地 qwen3:4b / qwen3.5:9b）/ Anthropic / OpenAI / MiniMax（ProviderInstance 可配置）|
| 记忆 | SQLite + LanceDB（向量检索）|
| 工具执行 | TaskExecutor（Strategy Pattern）|
| 子代理 | SubagentOrchestrator（独立会话 + 工具循环）|

## 快速开始

```bash
./jarvis.sh start   # 启动后端 + 前端
./jarvis.sh stop    # 停止所有服务
./jarvis.sh status  # 查看运行状态
```

## 本地模型配置

Jarvis 的多模态能力依赖本地推理模型。**首次启动前**请按本节准备好，否则语音/视觉/对话会失败。

### 模型清单

| 类别 | 模型 | 用途 | 大小 | 安装方式 |
|------|------|------|------|----------|
| **Chat** | `qwen3:4b` | 主对话 | ~2.5 GB | Ollama pull |
| **Vision** | `qwen3.5:9b` | 图片理解 | ~5.5 GB | Ollama pull |
| **STT** | Paraformer-large (funasr) | 中文语音转文字 | ~1 GB | 首次调用自动从 ModelScope 下载 |
| **T2I** *(可选)* | `x/z-image-turbo` | 文生图 | ~6 GB | Ollama pull |

### 1. 安装 Ollama + 拉取模型

Ollama 是 Jarvis 的本地推理核心，负责 Chat / Vision / T2I。

```bash
# macOS / Linux
brew install ollama   # 或访问 https://ollama.com/download
ollama serve          # 启动服务 (默认 http://localhost:11434)

# 拉取必需模型
ollama pull qwen3:4b        # 聊天
ollama pull qwen3.5:9b      # Vision

# (可选) 拉取 T2I
ollama pull x/z-image-turbo
```

验证：
```bash
ollama list
# 应看到 NAME           SIZE   MODIFIED
#       qwen3:4b        2.5 GB ...
#       qwen3.5:9b      5.5 GB ...
```

### 2. 安装 ffmpeg

**语音输入**需要 ffmpeg 解码浏览器录制的 WebM/Opus：

```bash
brew install ffmpeg     # macOS
sudo apt install ffmpeg # Ubuntu

ffmpeg -version  # 验证
```

### 3. STT 引擎 — Paraformer (推荐) / Whisper (备选)

| Backend | 中文质量 | 速度 (M3 Pro) | 模型来源 | 切换方式 |
|---------|----------|---------------|----------|----------|
| **Paraformer** (默认) | ⭐⭐⭐⭐⭐ 显著优于 whisper | ~500ms (MPS) | ModelScope 自动下载 | 无需配置 |
| Whisper | ⭐⭐⭐ 英文更好 | ~1.5s | `openai-whisper` 包 | `STT__BACKEND=whisper` |

**Paraformer 首次启动**：第一次语音请求会从 ModelScope 下载模型（~1GB），日志显示：
```
[Paraformer] loading model on mps...
[Paraformer] loaded on mps
```
模型缓存到 `~/.cache/modelscope/hub/`。

**切换 Whisper**（不推荐，中文质量下降）：
```bash
# .env 中加入
STT__BACKEND=whisper
# 并 pip install openai-whisper
pip install openai-whisper
```

### 4. Python 依赖

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

关键依赖：
- `funasr` + `torch` + `torchaudio` — Paraformer STT
- `httpx` — Ollama HTTP 客户端
- `fastapi` + `uvicorn` — 后端服务
- `lancedb` — 向量记忆

### 5. 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```bash
cp .env.example .env
```

常用项：
```bash
# Ollama
AI__OLLAMA__BASE_URL=http://localhost:11434
AI__OLLAMA__MODEL=qwen3:4b
AI__OLLAMA__VISION_MODEL=qwen3.5:9b

# STT (可选)
STT__BACKEND=paraformer        # paraformer | whisper
STT__BATCH_SIZE_S=300         # Paraformer 长音频切片大小

# 云端 LLM (可选, 用于 ProviderInstance)
AI__OPENAI__API_KEY=sk-xxx
AI__ANTHROPIC__API_KEY=sk-ant-xxx
```

> ⚠️ ProviderInstance 切换**不影响** STT——语音识别始终走本地 STT（paraformer/whisper），与 chat provider 解耦。这是已知设计：openai/anthropic/minimax 等 chat adapter 不实现 `transcribe_audio()`，直接返回空串。

### 6. 验证一切就绪

启动 backend 后访问 `http://localhost:9529/api/status`，应看到：

```json
{
  "ai": {
    "providers": {
      "ollama": {"configured": true}
    }
  },
  "sub_model_processor": {
    "stt_model": "...",
    "vision_model": "qwen3.5:9b",
    "router_ready": true
  }
}
```

**故障排查**：
- `Failed to connect to http://localhost:11434` → `ollama serve` 没跑
- `No module named 'funasr'` → `pip install funasr`
- `ffmpeg not found` → `brew install ffmpeg`
- 语音返回空串 → 检查 `logs/jarvis.services.sub_model_processor.log`，搜索 `[Paraformer]` / `[whisper]` 关键字

## 核心能力

| 能力 | 说明 | 触发方式 |
|------|------|----------|
| **听** | 语音识别（Paraformer / Whisper STT，本地推理）| 麦克风按钮 |
| **说** | 语音合成（浏览器 SpeechSynthesis）| 说"speak" |
| **读** | 文件/图片/PDF 读取 | 粘贴图片、文件上传 |
| **写** | 代码/文档生成、文件操作 | 直接对话 |
| **执行** | 工具调用（文件/Bash/浏览器/子代理...）| 对话中自然触发 |
| **追溯** | 每次 LLM 调用的 body + response 完整记录 | Settings → LLM 日志 |

## 子代理（Subagent）

主对话可将任务委派给隔离的子代理，每个子代理拥有独立会话：

| 角色 | 说明 |
|------|------|
| **Researcher** | 网络调研、多源信息收集 |
| **Coder** | 代码生成、执行、文件写入（带工具循环）|
| **Reviewer** | 代码/方案评审（优/问/建三段式）|
| **Summarizer** | 长文本摘要、结构化要点提取 |
| **Planner** | 任务拆解与验收标准 |
| **General** | 通用隔离子代理 |

主 LLM 通过 `subagent` 工具委派任务，支持串行（sequential）、并行（parallel）、map_reduce 三种编排模式。

## 工具系统

### 内置工具（TaskExecutor Strategy）

| 工具 | 说明 |
|------|------|
| `file` | 读写/编辑/列表/创建文件，带路径穿越保护 |
| `bash` | Shell 命令执行，含危险命令黑名单 |
| `browser` | Playwright 浏览器自动化 |
| `desktop` | pyautogui 桌面控制 |
| `api` | 外部 HTTP API 调用 |

### 技能（Skills）

通过 `Skill` 工具调用，技能定义在 `workspace/skills/` 目录，支持 markdown 编写 + YAML frontmatter 元数据。

## LLM 调用追溯

每次 LLM 调用（chat / stream / subagent / 工具迭代 / 主题生成 / 上下文压缩）都被完整记录：

**存储位置**：`workspace/logs/llm_calls/YYYY-MM-DD/`
- `index.jsonl` — 一行一条摘要（时间 / provider / model / latency / 状态 / 是否有工具调用）
- `<call_id>.json` — 完整详情（含 request body、response body、SSE chunks、thinking、tool_use）

**前端入口**：Settings → "LLM 日志"

**两种视图**：
- **按时间** — 平铺列表，按调用时间倒序
- **按会话** — 按 `conversation_id` 分组折叠，一次看到一次对话触发的所有 LLM 调用

**详情 4 Tab**：
- Request Body — 完整 messages + tools + 参数
- Response — content / thinking / content_blocks / usage
- Raw HTTP — 真实发到 provider 的 HTTP payload + 流式 SSE chunks
- Messages — 完整 messages 列表，按 role 彩色标签分组

**典型用例**：
- 排查"为什么这次对话跑了 30 秒" → 看 avg / p95 latency + 调用次数
- 复盘"subagent 的工具循环" → 按会话视图 → 展开看每次调用
- 排查 4xx/5xx 错误 → Raw HTTP tab 看 provider 返回

**清理**：按日期清空或一键清空所有日志。

详细设计见 [`模型请求数据追溯.md`](模型请求数据追溯.md)。

## 记忆系统

- **上下文压缩**：`ContextManager` 按 token 预算动态裁剪历史，注入相关记忆（top-k 向量检索）。
- **会话持久化**：对话保存到 SQLite，LanceDB 支持语义搜索。
- **独立子会话**：每个 subagent 调用创建独立 Conversation，父会话可跳转查看完整执行轨迹。

## 开发

```bash
# 后端（热重载）
uvicorn jarvis.main:app --reload --port 9529

# 前端（热重载）
cd frontend && npm run dev -- --port 8529

# 运行测试
python -m pytest tests/ -v
```

## 文档

- `CLAUDE.md` — 架构设计、技术细节、开发命令
- `DEVELOPMENT_PLAN.md` — 架构文档与功能路线图
- `DESIGN_PATTERNS.md` — 设计模式详解
- `bugs.md` — Bug 记录与解决方案
- `TODO.md` — 功能优先级
- `模型请求数据追溯.md` — LLM 调用日志系统设计与 Bug 修复记录

---

*Jarvis 系统，随时待命。*
