# BUGS 记录

记录发现的 bug 及解决方案，避免重复踩坑。

---

## 1. system_prompt 格式化 KeyError

**日期:** 2026-05-25

**错误信息:**
```
KeyError: '"action"'
```

**原因:**
`available_tools` 字符串中包含 JSON 示例：
```python
{"action": "read", "path": "file.txt"}
```
Python `str.format()` 把 `{action}` 解析为占位符，导致 KeyError。

**解决方案:**
使用字符串替换替代 `format()` 方法：
```python
def _build_system_prompt(self) -> str:
    return self.available_tools.replace("{work_folder}", self.work_folder)
```

**预防:**
- 避免在模板字符串中使用 `{` `}` 包裹可能与 format 语法冲突的内容
- 或使用 `{{}}` 转义，但需注意 `format()` 的 `{{}}` 会变成 `{}`

---

## 2. WebSocket 重复关闭错误

**日期:** 2026-05-25

**错误信息:**
```
RuntimeError: Unexpected ASGI message 'websocket.close', after sending 'websocket.close'
```

**原因:**
WebSocket 连接在 `finally` 块中调用 `close()`，但连接可能已经异常关闭。

**解决方案:**
```python
finally:
    ws_notifier.remove_connection(websocket)
    try:
        await websocket.close()
    except RuntimeError:
        pass  # WebSocket already closed
```

---

## 3. localStorage 日期反序列化错误

**日期:** 2026-05-25

**错误信息:**
```
Uncaught RangeError: Invalid time value
```

**原因:**
- `localStorage` 存储时日期被序列化为字符串
- 读取时未还原为 `Date` 对象
- `formatTime()` 收到字符串后 `new Date(string)` 失败

**解决方案:**
```typescript
// loadFromStorage 中使用 reviver
const parsed = JSON.parse(stored, (key, value) => {
  if (key === 'createdAt' || key === 'updatedAt' || key === 'timestamp') {
    return new Date(value)
  }
  return value
})

// formatTime 支持字符串
export function formatTime(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  ...
}
```

---

## 4. TaskExecutor 策略匹配问题

**日期:** 2026-05-25

**错误信息:**
文件操作返回 `{"status": "simulated", "tool": "file", ...}`

**原因:**
`execute_step` 中使用 `step.tool.split(".")[0]` 截取工具前缀，但 `tool="file"` 无 `.` 无法匹配到 `FileOperationStrategy`。

**解决方案:**
```python
async def execute_step(self, step: Step) -> Any:
    strategy = self.get_strategy(step.tool)  # 直接使用完整 tool 名称
    return await strategy.execute(step)
```

---

## 5. Ollama 流式响应空 token

**日期:** 2026-05-25

**问题:**
chat_stream 返回空 token

**原因:**
OllamaAdapter 使用了错误的 API 端点或参数

**解决方案:**
```python
async def chat_stream(self, messages: list[dict]):
    payload = {
        "model": self.model,
        "messages": messages,
        "stream": True
    }
    async with self.client.stream("POST", "/api/chat", json=payload) as response:
        async for line in response.aiter_lines():
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
```

---

## 6. 配置文件属性访问错误

**日期:** 2026-05-25

**错误信息:**
```
'Settings' object has no attribute 'sqlite_db_path'
```

**原因:**
配置重构后属性路径变化，如 `settings.sqlite_db_path` → `settings.storage.sqlite_db_path`

**解决方案:**
- 重构配置时保持属性路径一致性
- 或更新所有引用点

---

## 7. 日志模块循环导入

**日期:** 2026-05-25

**错误信息:**
循环导入导致 `settings` 为 None

**原因:**
`logger.py` 在模块级别导入 `jarvis.config`，而 config 可能依赖 logger

**解决方案:**
使用延迟导入：
```python
@classmethod
def _get_settings(cls):
    if cls._settings is None:
        from jarvis.config import settings
        cls._settings = settings
    return cls._settings
```

---

## 8. 文件操作路径穿越漏洞

**日期:** 2026-05-26

**问题:**
`_resolve_path()` 允许相对路径逃逸工作目录，如 `../../../etc/passwd`

**解决方案:**
使用 `Path.relative_to()` 验证路径：
```python
def _resolve_path(self, path: str) -> Path:
    work = Path(self.work_folder).resolve()
    p = Path(path).resolve()
    try:
        p.relative_to(work)
    except ValueError:
        raise PermissionError(f"路径穿越禁止: {path} 不在工作目录内")
    return p
```

---

## 9. 文件操作错误未触发日志通知

**日期:** 2026-05-26

**问题:**
`FileOperationStrategy` 的 `_read_file`、`_edit_file` 等方法在文件不存在等错误时直接返回 error dict，没有调用 `logger.error()`，导致 `NotificationLogHandler` 无法捕获并发送通知。

**原因:**
- `_read_file` 返回 `{"status": "error", "message": f"文件不存在: {path}"}` 时没有先记录错误
- `NotificationLogHandler.emit()` 只捕获 `record.levelno >= logging.ERROR` 的日志
- 异常被 `execute()` 的 `except Exception` 捕获并记录，但业务错误（如文件不存在）是正常返回的

**解决方案:**
在返回错误响应前先调用 `logger.error()` 记录错误：
```python
async def _read_file(self, path: str) -> dict:
    full_path = self._resolve_path(path)
    if not full_path.exists():
        logger.error(f"文件不存在: {path}")  # 添加日志
        return {"status": "error", "message": f"文件不存在: {path}"}
```

**预防:**
- 文件操作等策略在返回错误时，应先通过 logger 记录错误日志
- 或在策略层检查返回值，发现 error status 时主动发送通知