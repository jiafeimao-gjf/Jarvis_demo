# CLAUDE.md

JARVIS (贾维斯) 智能助手系统

## 项目路径
`/Users/jiafei/claude/Jarvis_demo`

## 快速启动

```bash
./jarvis.sh start   # 启动服务 (后端 9529 + 前端 8529)
./jarvis.sh stop    # 停止服务
./jarvis.sh status  # 查看状态
```

## 技术栈
- **后端**: Python / FastAPI / Ollama / Anthropic
- **前端**: Vue3 / TypeScript / Tailwind CSS / Pinia

## 关键文件
- `jarvis/main.py` - FastAPI 入口
- `jarvis/core/chat_engine.py` - 对话引擎
- `jarvis/services/ai/` - AI Provider 模块
- `frontend/src/composables/useApi.ts` - 前端 API 调用

## 核心功能
- 文字对话 + 流式响应
- 语音识别 / TTS
- 摄像头 / 视觉分析
- 工具调用 + 任务执行
- 记忆存储

## 文档
- `DEVELOPMENT_PLAN.md` - 开发计划
- `DESIGN_PATTERNS.md` - 设计模式
- `bugs.md` - BUG 记录
- `TODO.md` - 待办事项
- `README.md` - 项目说明