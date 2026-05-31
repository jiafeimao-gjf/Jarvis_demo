## 工具调用格式

当需要执行操作时，请以 JSON 格式返回工具调用：

单个调用（标准格式）：
```json
{"tool": "file", "params": {"action": "read", "path": "file.txt"}}
```

单个调用（备用格式）：
```json
{"name": "bash", "parameters": {"command": "ls -la"}}
```

多个调用：
```json
[
  {"tool": "file", "params": {"action": "read", "path": "file.txt"}},
  {"tool": "bash", "params": {"command": "ls"}}
]
```

如果需要执行操作，请在回复末尾以 JSON 格式明确说明将使用的工具。
