# 贾维斯（JARVIS）TODO

> 更新日期：2026-05-25

---

## 🔴 P0 - 立即处理

### 1-2. API 路由 + Ollama 模型名称
**状态**：✅ 已修复并提交

---

## 🟡 P1 - 功能完善

### 4. WebSocket 代理
**文件**：`frontend/vite.config.ts`
**状态**：✅ 已修复 (8000 → 9529)

### 5. .gitignore
**状态**：✅ 已创建

### 6. LanceDB 向量检索
**文件**：`jarvis/core/memory_store.py`
**问题**：初始化不稳定，fallback 到 SQLite
**修复**：
- [ ] 使用正确的 schema 定义
- [ ] 添加初始化重试
- [ ] 或接入专业向量数据库

**状态**：待修复

### 7. Stream 响应格式
**文件**：`jarvis/api/chat.py`
**状态**：✅ 已修复
- 后端添加 `chat_stream` 方法支持 SSE 流式输出
- 前端解析 SSE 格式正确

---

## 🟢 P2 - 优化项

### 8. 环境变量配置
**文件**：`.env.example`
**状态**：✅ 已创建

### 9. 基础单元测试
**需添加**：
- Backend: `pytest` + `pytest-asyncio`
- Frontend: `vitest` (已配置)
**状态**：待实现

### 10. TTS 完整流程
**问题**：需后端实现 Qwen3-TTS 支持
**状态**：待实现

### 11. 前端 Loading 动画
**文件**：`ChatWindow.vue`
**状态**：✅ 已优化 (打字机动画 + 改进加载动画)

### 12. CORS 生产配置
**文件**：`jarvis/main.py`
**状态**：✅ 已修复 (限制前端地址)

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
| 3 | Ollama 重试机制 (3次) | 2026-05-25 |
| 4 | WebSocket 代理修复 | 2026-05-25 |
| 5 | .gitignore 创建 | 2026-05-25 |
| 8 | .env.example 创建 | 2026-05-25 |
| 11 | Loading 动画优化 | 2026-05-25 |
| 12 | CORS 生产配置 | 2026-05-25 |

---

## 🔄 本次提交

```
[ddc6551] feat: 完成 P1/P2 待办项
- WebSocket 代理配置修复 (8000 → 9529)
- CORS 生产配置 (限制前端地址)
- 创建 .env.example 环境变量模板
- ChatWindow 流式响应支持
- ChatWindow 打字机动画优化
- Loading 动画改进
```

---

*TODO 将随项目进展持续更新*