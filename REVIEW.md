# 贾维斯（JARVIS）项目 Review

> Review 日期：2026-05-25

---

## 一、项目概览

| 指标 | 状态 |
|------|------|
| **代码量** | ~39 个源文件 (Python + Vue/TS) |
| **完成度** | 核心功能框架完成，细节待完善 |
| **可运行性** | ✅ 后端/前端可启动，需 Ollama 模型 |
| **测试状态** | ⚠️ 基础 API 测试通过，未做集成测试 |

---

## 二、发现的问题

### 🔴 P0 - 严重问题

| # | 问题 | 位置 | 说明 | 修复状态 |
|---|------|------|------|----------|
| 1 | **API 路由路径重复** | `jarvis/api/*.py` | 子路由 prefix 包含 `/api`，与主路由重复导致路径变成 `/api/api/chat` | ✅ 已修复 |
| 2 | **Ollama 模型名称错误** | `jarvis/config.py` | 配置 `qwen3` 但实际模型名是 `qwen3:4b` | ✅ 已修复 |

### 🟡 P1 - 功能问题

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 3 | **Ollama API 调用异常** | `jarvis/services/ollama_client.py` | `chat()` 方法未处理 Ollama 返回的错误格式 |
| 4 | **Stream 响应实现不完整** | `jarvis/api/chat.py` | `/chat/stream` 返回格式与前端期望不匹配 |
| 5 | **LanceDB 集成不稳定** | `jarvis/core/memory_store.py` | LanceDB 初始化会失败回退到 SQLite，向量检索功能不可用 |
| 6 | **任务执行策略未完整集成** | `jarvis/core/task_engine.py` | `BrowserAutomationStrategy` 和 `DesktopControlStrategy` 有异常处理但可能不稳定 |

### 🟢 P2 - 优化项

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 7 | **前端 TypeScript 类型不完整** | `frontend/src/types/index.ts` | 部分 Pydantic 模型字段未对应 |
| 8 | **缺少单元测试** | - | 无 pytest / vitest 测试 |
| 9 | **前端 API 代理配置** | `frontend/vite.config.ts` | `/ws` 代理未配置 |
| 10 | **缺少 .gitignore** | 项目根目录 | `node_modules/`、`venv/`、`.pyc` 未忽略 |
| 11 | **无环境变量配置文件** | - | 缺少 `.env.example` |
| 12 | **前端组件样式** | `ChatWindow.vue` | 深度滚动、loading 动画可优化 |

---

## 三、API 问题详情

### 问题 1：Ollama API 返回 404

**原因**：Ollama 服务器返回 404，但客户端错误处理不完善

**错误日志**：
```
Error: Client error '404 Not Found' for url 'http://localhost:11434/api/chat'
```

**分析**：
1. Ollama 的 `/api/chat` 端点需要 `messages` 格式
2. 可能是模型未正确加载或请求格式问题
3. 需要增强错误处理和重试逻辑

**建议修复**：
```python
async def chat(self, messages: list[dict], stream: bool = False) -> AIResponse:
    try:
        # 添加超时和错误重试
        ...
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.error(f"Model {self.model} not found or endpoint issue")
            # 回退到 generate 端点
        ...
```

---

## 四、代码质量评估

### 优点 ✅

1. **架构清晰**：Hexagonal Architecture 分层明确
2. **设计模式应用**：Mediator、Repository、Strategy、Observer、Pipeline 等模式使用得当
3. **类型定义**：Pydantic 模型 + TypeScript 类型定义
4. **日志完善**：结构化日志记录
5. **配置管理**：使用 pydantic-settings 集中管理

### 缺点 ⚠️

1. **异常处理不完善**：部分模块缺少 try-catch
2. **文档不足**：缺少 docstring 和注释
3. **代码重复**：部分 API 路由有重复模式
4. **前端状态管理**：Pinia store 可进一步解耦

---

## 五、安全评估

| 检查项 | 状态 | 说明 |
|------|------|------|
| **CORS** | ⚠️ | `allow_origins=["*"]` 生产环境需限制 |
| **输入验证** | ✅ | Pydantic 模型验证 |
| **敏感信息** | ⚠️ | 未使用 .env，配置明文 |
| **SQL 注入** | ✅ | 使用参数化查询 |
| **WebSocket 安全** | ❌ | 无认证机制 |

---

## 六、性能评估

| 指标 | 当前状态 | 目标 |
|------|----------|------|
| **API 响应时间** | ~200ms（无 Ollama） | <500ms |
| **前端加载时间** | ~1s | <2s |
| **并发连接** | 未测试 | 100+ |
| **内存占用** | 未测量 | <500MB |

---

## 七、依赖完整性

| 依赖 | 版本 | 状态 |
|------|------|------|
| fastapi | 0.115.0 | ✅ |
| uvicorn | 0.30.0 | ✅ |
| sse-starlette | 1.8.2 | ✅ |
| pydantic | 2.8.0 | ✅ |
| httpx | 0.27.0 | ✅ |
| lancedb | - | ⚠️ 未安装 |
| pyarrow | 14.0.0 | ✅ |
| playwright | - | ❌ 未安装 |
| pyautogui | - | ❌ 未安装 |

---

## 八、下一步行动建议

### 立即修复
1. 完善 Ollama API 错误处理
2. 添加 `/ws` 前端代理配置
3. 创建 `.gitignore`

### 短期优化
4. 添加基础单元测试
5. 完善前端 loading 状态
6. 实现 TTS 完整流程

### 长期规划
7. 添加用户认证
8. 接入专业的 embedding 服务
9. 性能优化和压力测试

---

*本 Review 将随项目进展持续更新*