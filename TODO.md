# 贾维斯（JARVIS）TODO

> 更新日期：2026-05-25

---

## 🔴 P0 - 立即处理

### 1. API 路由已修复 ✅

### 2. Ollama 模型名称已修复 ✅

### 3. Ollama API 错误处理

**文件**：`jarvis/services/ollama_client.py`

**问题**：chat() 方法遇到 404 或其他 HTTP 错误时直接返回错误字符串

**修复**：
- [ ] 添加重试机制（最多3次）
- [ ] 当 `/api/chat` 失败时回退到 `/api/generate`
- [ ] 区分模型未找到和端点问题
- [ ] 添加超时配置（目前 60s 可调整）

**状态**：待修复

---

## 🟡 P1 - 功能完善

### 4. 前端 WebSocket 代理

**文件**：`frontend/vite.config.ts`

**问题**：`/ws` 路由未配置代理，前端无法连接 WebSocket

**修复**：
```typescript
'/ws': {
  target: 'ws://localhost:9529',
  ws: true
}
```

**状态**：待修复

### 5. 创建 .gitignore

**文件**：项目根目录

**内容**：
```
# Python
__pycache__/
*.py[cod]
venv/
*.egg-info/
.eggs/

# Frontend
node_modules/
dist/
.DS_Store

# IDE
.idea/
.vscode/
*.swp

# Logs
logs/
*.log

# Memory
memory/
```

**状态**：待创建

### 6. LanceDB 向量检索

**文件**：`jarvis/core/memory_store.py`

**问题**：LanceDB 初始化不稳定，fallback 到 SQLite 导致向量检索功能不可用

**修复**：
- [ ] 使用正确的 schema 定义
- [ ] 添加初始化重试
- [ ] 或接入专业向量数据库（如 Milvus、Qdrant）

**状态**：待修复

### 7. Stream 响应格式

**文件**：`jarvis/api/chat.py`

**问题**：前端期望 SSE 格式与后端实际输出不匹配

**修复**：
- [ ] 统一 SSE 事件格式
- [ ] 添加 `onDone` 回调处理
- [ ] 测试完整流式对话流程

**状态**：待修复

---

## 🟢 P2 - 优化项

### 8. 环境变量配置

**文件**：`.env.example`

**内容**：
```
# Backend
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_VISION_MODEL=qwen3-vl:4b
PORT=9529

# Frontend
VITE_API_URL=http://localhost:9529
```

**状态**：待创建

### 9. 基础单元测试

**需添加**：
- Backend: `pytest` + `pytest-asyncio`
- Frontend: `vitest` (已配置)

**测试文件**：
```
tests/
├── test_chat_engine.py
├── test_memory_store.py
├── test_api_chat.py
└── test_task_engine.py
```

**状态**：待实现

### 10. TTS 完整流程

**文件**：
- `jarvis/api/voice.py`
- `frontend/src/composables/useSpeechRecognition.ts`

**问题**：TTS 使用浏览器 `speechSynthesis`，需要在后端添加 Qwen3-TTS 支持

**修复**：
- [ ] 后端实现 Qwen3-TTS 调用
- [ ] 前端对接后端 TTS API
- [ ] 音频流传输

**状态**：待实现

### 11. 前端 Loading 动画优化

**文件**：`frontend/src/components/ChatWindow.vue`

**优化**：
- [ ] 打字机效果显示
- [ ] 脉冲动画改进
- [ ] 消息发送成功/失败状态

**状态**：待优化

### 12. CORS 生产配置

**文件**：`jarvis/main.py`

**修复**：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8529"],  # 限制为前端地址
    allow_credentials=True,
    allow_methods=["GET", "POST", "WS"],
    allow_headers=["*"],
)
```

**状态**：待修复

---

## 📋 长期规划

### 13. 用户认证
- [ ] JWT Token 认证
- [ ] WebSocket 鉴权
- [ ] 会话管理

### 14. 专业 Embedding 服务
- [ ] 接入 OpenAI Embedding
- [ ] 或本地 Embedding 模型
- [ ] 改善记忆检索质量

### 15. 性能优化
- [ ] 添加缓存层（Redis）
- [ ] API 响应压缩
- [ ] 前端代码分割

### 16. 移动端适配
- [ ] 响应式布局优化
- [ ] 触摸交互支持
- [ ] PWA 支持

### 17. 部署文档
- [ ] Docker 配置
- [ ] Nginx 配置
- [ ] Systemd 服务文件

---

## ✅ 已完成

| 序号 | 任务 | 完成日期 |
|------|------|----------|
| 1 | API 路由路径重复修复 | 2026-05-25 |
| 2 | Ollama 模型名称修复 | 2026-05-25 |

---

*TODO 将随项目进展持续更新*