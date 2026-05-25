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

### 18. 系统配置页面
**文件**：`frontend/src/components/Settings.vue`
**功能**：
- 显示服务器/AI/硬件/存储配置
- 可编辑服务器端口、AI默认Provider/模型、Ollama配置
- 调用 PUT /api/config 更新配置
**状态**：✅ 已完成

### 19. 配置系统重构
**文件**：`jarvis/config.py`
**功能**：
- 嵌套配置结构 (ServerConfig, CORSConfig, AIConfig, HardwareConfig, StorageConfig)
- 环境变量支持嵌套格式 (AI__OLLAMA__MODEL)
- ConfigManager 运行时配置管理
- GET/PUT /api/config API
**状态**：✅ 已完成

### 20. 多 Provider AI 模块
**文件**：`jarvis/services/ai/`
**功能**：
- 支持 Ollama/OpenAI/Anthropic 三个 Provider
- ProviderRegistry 注册表模式
- AIRouter 自动故障转移
- 模型选择支持 (model 参数)
**状态**：✅ 已完成

### 21. 对话持久化
**文件**：`frontend/src/stores/chat.ts`
**功能**：
- localStorage 持久化对话列表
- 页面刷新不丢失对话
- 自动同步到后端 SQLite
- 对话列表和删除功能
**状态**：✅ 已完成

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