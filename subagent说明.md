# Subagent 模块使用说明

> 最后更新：2026-07-02
> 适用版本：JARVIS v2（含 ContextManager + SubagentOrchestrator）

---

## 🎯 一句话回答：会自动触发吗？

**不会。Subagent 必须由主 LLM 显式调用 `subagent` 工具才会触发。**

设计原因：

- 自动委派会让系统行为不可预测（用户不知道哪次对话走了子代理、消耗了多少 token）
- 主 LLM 是唯一能判断"这个任务值不值得开子代理"的角色
- 用户应该能通过 prompt 引导："遇到复杂调研请用 subagent 工具"

如果你想要"自动触发"，需要在 `ChatEngine` 里加一层意图识别（比如检查任务关键词、或者再调一次轻量 LLM 分类），目前没做。

---

## 🔄 完整工作流

```
用户: "调研 3 个数据库对比，输出选型报告"
                    │
                    ▼
       主 LLM (chat_engine.stream_chat)
       读到 system_prompt 中 subagent 工具 schema
                    │
                    ▼
       主 LLM 输出 tool_use:
       {
         "name": "subagent",
         "input": {
           "mode": "map_reduce",
           "tasks": [
             {"role": "researcher", "task": "调研 PostgreSQL"},
             {"role": "researcher", "task": "调研 MySQL"},
             {"role": "researcher", "task": "调研 MongoDB"}
           ],
           "reduce_prompt": "对比三者, 输出选型报告"
         }
       }
                    │
                    ▼
       ChatEngine 解析 tool_use → Step(tool="subagent", params=...)
                    │
                    ▼
       TaskExecutor.execute_step(step)
                    │
                    ▼
       SubagentStrategy.execute(step)            ← jarvis/core/task_engine.py
                    │
                    ├─ 解析 params (mode + tasks)
                    ├─ 构造 DispatchRequest 列表
                    │
                    ▼
       SubagentOrchestrator.run_batch(MAP_REDUCE, requests)
                    │
                    ├─ asyncio.gather([
                    │     ResearcherSubagent.run("调研 PostgreSQL"),
                    │     ResearcherSubagent.run("调研 MySQL"),
                    │     ResearcherSubagent.run("调研 MongoDB"),
                    │   ])
                    │   三个隔离 LLM 调用，并行执行
                    │
                    ├─ reducer 把 3 个输出拼成 markdown
                    │
                    ├─ 调一次 LLM 综合 (reduce_prompt) → 最终报告
                    │
                    └─ 返回 DispatchBatchResult
                    │
                    ▼
       SubagentStrategy.format 结果为纯文本
                    │
                    ▼
       作为 tool_result 消息回注主对话
       {"role": "user", "content": "[子代理结果] mode=map_reduce ...\n<报告内容>"}
                    │
                    ▼
       主 LLM 拿到结果，生成最终回复给用户
```

---

## 📞 主 LLM 怎么调用？— 工具调用格式

### 单任务调用

```json
{
  "name": "subagent",
  "input": {
    "role": "researcher",
    "task": "调研向量数据库在 2026 年的主流选型",
    "context": "用户在做 RAG 项目, 规模约 10 万条文档"   // 可选
  }
}
```

返回（主 LLM 看到的 tool_result）：
```
[子代理结果]
角色: researcher
任务: 调研向量数据库在 2026 年的主流选型
耗时: 8.3s
输出:
## 主流向量数据库 2026 调研

### 1. Pinecone
- 托管服务, 易用...
### 2. Weaviate
- 开源, 支持混合检索...
...
```

### 批量子任务（并行）

```json
{
  "name": "subagent",
  "input": {
    "mode": "parallel",
    "tasks": [
      {"role": "researcher", "task": "调研 Pinecone"},
      {"role": "researcher", "task": "调研 Weaviate"},
      {"role": "researcher", "task": "调研 Qdrant"}
    ]
  }
}
```

`mode` 可选：`sequential`（默认）/ `parallel` / `map_reduce`

---

## 🧩 三种编排模式

| 模式 | 行为 | 适用场景 |
|---|---|---|
| `sequential` | 顺序执行，下一个任务的 context 自动追加前面所有输出 | 流水线：A 调研 → B 基于 A 写代码 → C 基于 B 复审 |
| `parallel` | `asyncio.gather` 真正并行执行 | 独立任务：调研多个方案、批量生成、并发 IO |
| `map_reduce` | 并行 + 可选 LLM 二次综合 (`reduce_prompt`) | 多源汇总、对比报告、聚合统计 |

### 顺序模式的 context 串联示例

```python
batch = [
    DispatchRequest(SubagentRole.PLANNER,    "拆解任务"),
    DispatchRequest(SubagentRole.CODER,      "基于上一步实现"),  # 自动看到 plan 输出
    DispatchRequest(SubagentRole.REVIEWER,   "基于上一步复审"),  # 自动看到 code 输出
]
await orch.run_batch(DispatchMode.SEQUENTIAL, batch)
```

第二个任务实际收到的 system+user 消息：

```
system: 你是一名严谨的软件工程师...
[背景上下文]
[先前子代理输出]
[summarizer] ## 任务拆解
1. 实现 ...
2. 测试 ...
user: 基于上一步实现
```

---

## 🤖 6 个内置角色

| 角色 | system_prompt 关键约束 | 典型用途 |
|---|---|---|
| `researcher` | 客观、可验证、引用来源、不编造 | 信息收集、市场调研、技术对比 |
| `coder` | 先思路后代码、自包含、加注释、边界处理 | 写脚本、实现功能、写单测 |
| `reviewer` | 优/问/建三段式、具体到行/段、可执行建议 | 代码 review、方案 review、文档 review |
| `summarizer` | 保留关键事实、删除冗余、不超过原文 25% | 长文摘要、会议纪要、文章要点 |
| `planner` | 3-7 步拆解、输入/产出/依赖/风险、DoD | 任务规划、sprint planning、学习路径 |
| `general` | 通用助手、隔离上下文、简洁输出 | 不确定时兜底 |

每个角色都有独立的 system_prompt（见 `jarvis/core/subagent.py` 各个 `build_system_prompt()` 方法）。

---

## 💻 代码层用法（绕过 LLM 直接调）

如果想在 Python 代码里直接用（不通过 LLM 工具调用）：

```python
from jarvis.core.subagent import (
    SubagentOrchestrator, SubagentRole, DispatchMode, DispatchRequest
)

orch = SubagentOrchestrator(
    router=chat_engine.router,         # 复用 ChatEngine 的 AIRouter
    work_folder="/path/to/workspace",
)

# 单任务
result = await orch.run_one(
    SubagentRole.CODER,
    task="写一个 Python 函数, 计算斐波那契数列第 n 项",
    context="用户偏好递归实现, 加 memoization",
)
print(result.output)

# 批量并行
batch = [
    DispatchRequest(SubagentRole.SUMMARIZER, "总结文章 A"),
    DispatchRequest(SubagentRole.SUMMARIZER, "总结文章 B"),
]
out = await orch.run_batch(DispatchMode.PARALLEL, batch)

# map_reduce + reduce_prompt
out = await orch.run_batch(
    DispatchMode.MAP_REDUCE,
    batch,
    reduce_prompt="对比两篇文章的观点异同",
)
print(out.reduced_output)  # 综合后的文本
```

`SubagentOrchestrator` 已经是 `ChatEngine` 的成员：

```python
chat_engine.subagent_orchestrator  # 实例
chat_engine.task_executor          # 已注册 subagent strategy
```

---

## ⚙️ 关键配置（SubagentConfig）

每个子代理可以独立配置：

```python
from jarvis.core.subagent import SubagentConfig, SubagentRole

config = SubagentConfig(
    role=SubagentRole.RESEARCHER,
    system_prompt="你是一名...",        # 必填
    allowed_tools=["web_search", "file"],  # 限制可见工具 (扩展点, 当前未用)
    model="claude-3-5-sonnet",        # None = 跟随主代理
    max_iterations=5,                 # 子代理内部 tool 循环上限 (当前未启用, 见下方"局限")
    max_tokens_output=2048,
    temperature=0.3,
    timeout=120.0,                    # 总超时 (秒)
)
```

也可以在工厂方法里通过 `config_overrides` 临时覆盖：

```python
agent = create_subagent(
    SubagentRole.CODER,
    router=router,
    config_overrides={"temperature": 0.1, "timeout": 60.0},
)
```

---

## 🔌 集成位置

| 位置 | 文件 | 作用 |
|---|---|---|
| 主 LLM 工具暴露 | `jarvis/core/tool_registry.py` | 注册 `subagent` 工具 schema |
| 工具分发 | `jarvis/core/task_engine.py` (`SubagentStrategy`) | 解析 LLM 的工具参数 |
| 角色与编排 | `jarvis/core/subagent.py` | 6 个角色 + Orchestrator |
| ChatEngine 注入 | `jarvis/core/chat_engine.py` (`__init__`) | `SubagentOrchestrator` + `register_subagent()` |
| Mediator 暴露 | 当前没有直接暴露 | 如需外部触发可加 `mediator.dispatch_subagent()` |

---

## 🧪 测试覆盖

`tests/test_subagent.py` 包含 24 个用例：

- `TestFactory` — 6 个角色 + 字符串解析 + 未知角色降级 + 配置覆盖
- `TestRoleSystemPrompts` — 每个角色 system_prompt 关键字 + 包含任务
- `TestRunSingle` — 成功 / 带 context / LLM 异常 / 超时
- `TestOrchestrator` — run_one / 串行 context 串联 / 并行耗时验证 / map_reduce / 空批
- `TestSubagentStrategy` — 未注入报错 / 单任务 / 批量并行 / 未知 role 降级 / 空 batch
- `TestTaskExecutorRegistration` — register_subagent 接入 / 类型校验 / 端到端 execute_step
- `TestSerialization` — to_dict 输出格式

总计 **135 个测试全部通过**（24 Subagent + 28 ContextManager + 83 原有）。

---

## 🧭 实践建议：什么时候让主 LLM 调 subagent

在主 LLM 的 system_prompt 里可以加一句提示，引导它正确使用：

```markdown
## subagent 工具使用指引

当用户请求满足以下任一条件时，优先使用 subagent 工具：
1. 需要多源信息收集（"调研 X / 查资料 / 对比方案"）
2. 需要隔离上下文的复杂子任务（"写代码 + 复审" 流水线）
3. 多个独立任务可并行（"分别生成 A/B/C"）
4. 主对话上下文已经很长，避免再注入大量工具结果

role 选择指南：
- 调研类 → researcher
- 代码生成 → coder
- 复审已有方案 → reviewer
- 长文摘要 → summarizer
- 任务拆解 → planner
- 不确定 → general

mode 选择：
- 独立任务 → parallel
- 后一步依赖前一步 → sequential
- 多源汇总出报告 → map_reduce + reduce_prompt
```

---

## 🚧 已知局限 / 后续可优化

1. **子代理内部不能调 subagent 工具** — 当前 `BaseSubagent.run()` 只调一次 LLM，不进入工具循环。要让 researcher 能自己调 `web_search` 子工具，需要扩展 `BaseSubagent` 加 `tool_loop` 逻辑。

2. **`allowed_tools` 配置未生效** — 数据结构有，但 `SubagentStrategy.execute` 没读这个字段。要做权限隔离需要在 `BaseSubagent.run` 里把 tool schema 过滤后传给 LLM。

3. **子代理不知道主对话上下文** — 当前 `run(task, context)` 的 `context` 只能由调用方手动传。要让子代理自动看到主对话相关片段，需要在 `ChatEngine` 里把最近 N 条 user/assistant 摘要后注入。

4. **没有结果缓存** — 同样的子任务重复触发会重新调 LLM。可以加 `SubagentOrchestrator.cache_key(task, role)` 做一层短期缓存。

5. **没有成本/超时控制** — 一次 `map_reduce` 调 100 个 researcher 可能并发 100 个 LLM 调用。要加 semaphore 限流：

```python
sem = asyncio.Semaphore(5)
async def run_with_sem(req):
    async with sem:
        return await orch.run_one(req.role, req.task)
results = await asyncio.gather(*[run_with_sem(r) for r in requests])
```

6. **没有"自动触发"机制** — 如果想根据任务关键词自动派单，可以加一个 `IntentRouter`：先用小模型分类（`research` / `code` / `chitchat`），是研究类就强制走 subagent。

---

## 📚 相关文档

- `CLAUDE.md` — Subagent Module 章节
- `上下文管理说明.md` — ContextManager 说明
- `jarvis_architecture_v2.puml` / `.png` — 架构图（SubagentOrchestrator 橙色高亮）
- `tests/test_subagent.py` — 单元测试 + 用法示例

---

*文档随模块迭代更新，版本 v2.0*