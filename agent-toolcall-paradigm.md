# AI Agent 工具调用消息构造范式与约束

> 一次完整 Agent 轮次中，Agent 可能需要多次调用大模型完成最终目标。本文档定义消息构造范式及其约束，以适配大部分主流模型。

## 目录

- [一、核心范式：累积式消息数组](#一核心范式累积式消息数组)
- [二、通用约束（两协议共有）](#二通用约束两协议共有)
- [三、OpenAI 协议范式](#三openai-协议范式)
- [四、Anthropic Claude 协议范式](#四anthropic-claude-协议范式)
- [五、跨协议适配要点](#五跨协议适配要点)
- [六、Agent 循环伪代码](#六agent-循环伪代码)

---

## 一、核心范式：累积式消息数组

一轮 Agent 推理中，消息数组是**累积增长**的——每次 LLM 调用都接收完整历史（含此前所有工具调用与结果）。

```
while not done:
    resp = llm.chat(messages, tools=tool_schema)        # 1 次 LLM 推理
    if resp.tool_calls:
        messages.append(assistant_msg_with_tool_calls)  # 含 tool_calls
        for tc in resp.tool_calls:
            result = execute(tc)                         # 执行工具
            messages.append(tool_result_msg)             # 结果回填
    else:
        messages.append(assistant_final_answer)          # 终止
        done = True
```

### 消息角色总览

| 角色 | 说明 |
|------|------|
| `system` | 角色/工具说明（位置因协议而异） |
| `user` | 用户输入；Anthropic 中也承载工具结果 |
| `assistant` | 模型输出，可含文本与工具调用 |
| `tool`（OpenAI 专有） | 工具执行结果 |

---

## 二、通用约束（两协议共有）

| 约束 | 规则 |
|------|------|
| **完整性约束** | 每个 `tool_call` 必须有对应的工具结果；无孤儿调用、无孤儿结果 |
| **配对约束** | 调用 ID 与结果 ID 严格一致；ID 在整个会话中全局唯一 |
| **顺序约束** | 工具结果必须紧跟触发它的 assistant 消息之后；下一轮 assistant 之前所有结果须就位 |
| **并行约束** | 单个 assistant 消息内多个 `tool_calls` = 并行执行；结果顺序不限，但必须全部到齐 |
| **单次推理边界** | 一个含 `tool_calls` 的 assistant 消息 = 一次 LLM 推理；不可人为合并多个思考步 |
| **工具定义一致性** | 每次传给 LLM 的工具 schema 应保持一致，除非有意变更可用工具集 |

---

## 三、OpenAI 协议范式

> 适用模型：GPT、DeepSeek、Qwen、GLM、Mistral 等 OpenAI 兼容 API。

### 3.1 消息角色与字段

| 角色 | 关键字段 | 说明 |
|------|---------|------|
| `system` | `content`(string) | 置于 `messages[0]` |
| `user` | `content`(string) | 用户输入 |
| `assistant` | `content`(string\|null) + `tool_calls`(array) | 可同时含文本与工具调用 |
| `tool` | `tool_call_id` + `content`(string) | 独立角色承载工具结果 |

### 3.2 工具定义（`tools` 参数）

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询城市天气",
    "parameters": {
      "type": "object",
      "properties": { "city": { "type": "string" } },
      "required": ["city"]
    }
  }
}
```

- 字段名：`parameters`（JSON Schema 对象）

### 3.3 调用与结果消息

```json
// assistant 调用工具
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_a",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"city\":\"北京\"}"
      }
    }
  ]
}

// tool 结果
{
  "role": "tool",
  "tool_call_id": "call_a",
  "content": "25°C 晴"
}
```

### 3.4 OpenAI 专属约束

| 约束 | 规则 |
|------|------|
| **arguments 字符串化** | `function.arguments` 是 **JSON 字符串**，非已解析对象 |
| **独立 tool 角色** | 工具结果用 `role="tool"`，不在 user 消息内 |
| **content 灵活** | assistant 的 `content` 可为 `string` 或 `null` |
| **配对键** | `tool_call_id`（调用侧 `id`，结果侧 `tool_call_id`） |

---

## 四、Anthropic Claude 协议范式

> 适用模型：Claude 系列。用 **content block 数组**表达一切，无独立 `tool` 角色。

### 4.1 消息角色与字段

| 角色 | content 类型 | 说明 |
|------|-------------|------|
| `system` | 顶层 `system` 参数（不在 messages 内） | 单独传入 |
| `user` | `content`(array) | 可含 `text` 块、`tool_result` 块 |
| `assistant` | `content`(array) | 可含 `text` 块、`tool_use` 块 |

> 关键：**没有 `tool` 角色**，工具结果放在 `user` 消息内（`tool_result` content block）。

### 4.2 工具定义（`tools` 参数）

```json
{
  "name": "get_weather",
  "description": "查询城市天气",
  "input_schema": {
    "type": "object",
    "properties": { "city": { "type": "string" } },
    "required": ["city"]
  }
}
```

- 字段名：`input_schema`（非 `parameters`）

### 4.3 调用与结果消息

```json
// assistant 调用工具（tool_use 块）
{
  "role": "assistant",
  "content": [
    { "type": "text", "text": "我来查一下" },
    {
      "type": "tool_use",
      "id": "toolu_a",
      "name": "get_weather",
      "input": { "city": "北京" }
    }
  ]
}

// user 承载工具结果（tool_result 块）
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_a",
      "content": "25°C 晴"
    }
  ]
}
```

### 4.4 Anthropic 专属约束

| 约束 | 规则 |
|------|------|
| **input 对象化** | `input` 是 **JSON 对象**，非字符串 |
| **结果在 user 内** | 工具结果用 `role="user"` + `tool_result` content block |
| **content 恒为数组** | `content` 始终是 content block 数组 |
| **配对键** | 调用侧 `id`，结果侧 `tool_use_id` |

---

## 五、跨协议适配要点

写转换层时，重点处理以下三处：

| 差异点 | OpenAI | Anthropic | 适配操作 |
|--------|--------|-----------|---------|
| 结果角色 | `role="tool"` | `role="user"` + `tool_result` block | 角色映射 |
| 参数值类型 | `arguments` = JSON 字符串 | `input` = JSON 对象 | `JSON.parse` / `JSON.stringify` |
| 配对键名 | `tool_call_id` | `tool_use_id` | 键名替换 |
| 工具定义字段 | `parameters` | `input_schema` | 字段重命名 |
| content 形态 | `string` \| `null` | 恒为 `block[]` | 包装/解包 content block |
| system 位置 | `messages[0]` | 顶层 `system` 参数 | 提取/塞入 |

> 处理好这三处（角色映射 / 参数类型 / 配对键名），即可用一套统一的 Agent 内部循环逻辑同时驱动两类模型。

---

## 六、Agent 循环伪代码

```python
def agent_round(messages, tools, llm_client):
    """一次完整 Agent 轮次：可能多次调用 LLM 直到产出最终答案"""
    done = False
    while not done:
        # 1 次 LLM 推理
        resp = llm_client.chat(messages=messages, tools=tools)

        if resp.tool_calls:
            # 追加 assistant 消息（含 tool_calls）
            messages.append(resp.to_message())

            # 执行每个工具调用并回填结果
            for tool_call in resp.tool_calls:
                result = execute_tool(tool_call)
                messages.append(build_tool_result_message(tool_call, result))
            # 循环继续 → 下一次 LLM 推理
        else:
            # 无工具调用 → 最终答案，终止
            messages.append(resp.to_message())
            done = True

    return messages
```

> `build_tool_result_message` 与 `resp.to_message()` 的实现取决于目标协议（OpenAI / Anthropic）。
