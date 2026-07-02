# BUGS 记录

记录发现的 bug 及解决方案，避免重复踩坑。

---

## 1. system_prompt 格式化 KeyError

**日期:** 2026-05-25

**原因:** `str.format()` 把 `{action}` 解析为占位符

**解决:** 使用字符串替换替代 `format()` 方法

---

## 2. WebSocket 重复关闭错误

**日期:** 2026-05-25

**原因:** `finally` 块中调用 `close()` 时连接可能已关闭

**解决:** 添加 try-except 捕获 RuntimeError

---

## 3. localStorage 日期反序列化错误

**日期:** 2026-05-25

**原因:** 日期被序列化为字符串，读取时未还原

**解决:** 使用 JSON.parse reviver 或 `formatTime` 支持字符串

---

## 4. TaskExecutor 策略匹配问题

**日期:** 2026-05-25

**原因:** `tool.split(".")[0]` 无法匹配无 `.` 的工具名

**解决:** 直接使用完整 tool 名称匹配

---

## 5. Ollama 流式响应空 token

**日期:** 2026-05-25

**原因:** 使用了错误的 API 端点或参数

**解决:** 使用 `/api/chat` 端点并检查 `message.content`

---

## 6. 配置文件属性访问错误

**日期:** 2026-05-25

**原因:** 配置重构后属性路径变化

**解决:** 保持属性路径一致性或更新引用

---

## 7. 日志模块循环导入

**日期:** 2026-05-25

**原因:** logger.py 循环依赖 config

**解决:** 使用延迟导入

---

## 8. 文件操作路径穿越漏洞

**日期:** 2026-05-26

**原因:** 相对路径可逃逸工作目录

**解决:** 使用 `Path.relative_to()` 验证路径

---

## 9. 文件操作错误未触发日志通知

**日期:** 2026-05-26

**原因:** 错误响应未调用 `logger.error()`

**解决:** 返回错误前先记录日志

---

## 10. 选择对话后消息为空

**日期:** 2026-05-27

**原因:** `selectConversation` 只更新 ID，未加载消息

**解决:** 检查 messages 为空时调用 API 获取

---

## 11. syncToBackend 无重试机制

**日期:** 2026-05-27

**原因:** 失败时无重试，可能丢失消息

**解决:** 添加重试机制

---

## 12. MiniMax 工具调用格式不兼容

**日期:** 2026-05-27

**原因:** MiniMax 返回 `{"name": ..., "parameters": {...}}`，解析器只支持 `{"tool": ..., "params": {...}}`

**解决:** `ToolCallParser` 支持两种格式

---

## 13. POST /memory/conversation/{id} 422 错误

**日期:** 2026-05-27

**原因:** FastAPI 将字段当作 query 参数处理

**解决:** 改用 `Request.json()` 直接解析

---

## 14. 模型选择与后端不一致

**日期:** 2026-05-27

**原因:** 前端带 model 不带 provider，后端用默认值

**解决:** 前端添加 model，后端用 model 的 provider

---

## 15. 工具调用 content_blocks 解析失败

**日期:** 2026-05-28

**原因:** LLM 返回空 content 但 has_tool_calls=True，content_blocks 未正确提取

**状态:** 🔍 调试中

---

## 16. Subagent 调用模型与主对话不一致

**日期:** 2026-07-02

**现象:** 主对话用用户选定的 `model` + 解析出的 `ProviderInstance` 调 LLM，但通过 `subagent` 工具委派的子任务用了全局默认模型、且绑不到自定义 Provider 实例（如 MiniMax 代理）。MAP_REDUCE 的 reduce 阶段同理。

**原因:**
1. `BaseSubagent.run()` 调 `router.chat(messages, model=self.config.model, ...)`，而 `SubagentConfig.model` 默认 `None` → router 回退到 `self.config.default_model`（全局默认），忽略了主对话用户选的模型。
2. subagent 调用完全没传 `instance`，用户配置的自定义 `ProviderInstance` 不会被使用。
3. `SubagentOrchestrator` 的 MAP_REDUCE reduce LLM 调用既没传 model 也没传 instance。
4. `router.chat()` 本身不支持 `instance` 参数（只有 `chat_stream` / `chat_stream_full` 支持），导致即使想传也传不进去。

**解决:**
- `services/ai/router.py`: `chat()` 新增 `instance` 参数，绑定时走 `_get_client_with_instance` 并跳过 fallback chain，行为与 `chat_stream_full` 对齐。
- `core/subagent.py`: `BaseSubagent` / `create_subagent` / `SubagentOrchestrator` 新增 `main_model` + `instance` 字段；`run()` 用 `self.config.model or self.main_model` + `self.instance` 调 `router.chat`；reduce 阶段同样传入 `self.model` / `self.instance`。
- `core/chat_engine.py`: `chat` / `stream_chat` / `stream_chat_with_messages` 三处每次对话注入 `subagent_orchestrator.model = model` 和 `.instance = _resolve_instance(provider_id)`。

**优先级:** `SubagentConfig.model`（显式 per-subagent 覆盖）> 主对话模型 > router 默认。保留了"子代理可用不同模型"的扩展点，默认行为与主对话保持一致。

**验证:** `tests/` 全部 191 个测试通过（含 `test_subagent.py` / `test_router_instance.py`）。

---

## 17. 工具迭代 / 主题生成的 LLM 调用未传 instance，自定义 Provider 模型报 "All providers failed"

**日期:** 2026-07-02

**现象:** 用户选用自定义 ProviderInstance（模型 `glm-5.2`，不在内置 `MODELS` 注册表里）对话。当主 LLM 调用 `subagent` 工具后，主对话进入第二阶段再次调用 LLM 时报错：

```
2026-07-02 22:57:01 - jarvis.api.chat - ERROR - Stream chat error: All providers failed:
```

错误消息为空（`errors` 列表为空）。subagent 本身执行成功（`status=success`），崩溃发生在 subagent 返回后主对话的工具后 LLM 调用。

**原因:** `ChatEngine` 里只有第一阶段的 `chat_stream_full(..., instance=instance)` 传了 `instance`，而以下调用都漏了 `instance`：

1. `chat()` 工具迭代循环里的 `router.chat(messages, model=model, stream=False)`（首次及后续 LLM 调用）。
2. `stream_chat()` / `stream_chat_with_messages()` 工具执行后的 `router.chat(messages, model=model, stream=False)`。
3. `generate_topic()` → `router.chat(messages, model=model, ...)`（主题生成，有 fallback 不会崩，但会静默回退到首句截断）。

模型 `glm-5.2` 不在 `MODELS` 注册表 → `router._chain()` 中 `get_model()` 返回 `None` → 没有 `model_info.provider`、`preferred` 也为 `None` → 若 `fallback_chain` 也为空，`providers` 列表为空 → for 循环不执行 → `errors` 为空 → 抛 `AllProvidersFailedError` 且消息为空。

**解决:**
- `chat_engine.py`: 三处入口 (`chat` / `stream_chat` / `stream_chat_with_messages`) 各自只解析一次 `instance = self._resolve_instance(provider_id)`，复用给：
  - 主对话 LLM 调用（含工具迭代后的 `router.chat`，全部加 `instance=instance`）；
  - subagent 编排器 (`orchestrator.instance = instance`)；
  - 主题生成 (`_generate_and_yield_topic(..., instance=instance)` 与 `chat()` 内的 `generate_topic(..., instance=instance)`)。
- `topic_generator.py`: `generate_topic()` 新增 `instance` 参数并透传给 `router.chat`。

**原则:** 一次对话内所有 LLM 调用（主对话 / 工具迭代 / subagent / reduce / 主题生成）必须共用同一个 `model` + `ProviderInstance`，任何一处漏传 `instance` 都会让自定义 Provider 模型落到 fallback chain 上而失败。

**验证:** `tests/` 全部 191 个测试通过；用 `glm-5.2` 实例复测 subagent 工具调用后主对话不再报 "All providers failed"。

---

*持续更新*