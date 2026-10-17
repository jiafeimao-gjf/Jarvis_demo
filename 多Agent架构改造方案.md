# JARVIS 多 Agent 架构改造方案

> 状态：设计方案（待实施）
> 基线：当前 main 分支（2026-09-30），测试基线 275 passed / 4 failed（既有失败，见附录 A）
> 关联文档：`subagent独立会话方案.md`（v3，子会话部分已落地）、`CLAUDE.md`、`DESIGN_PATTERNS.md`

---

## 0. 摘要与需求映射

把现有的「硬编码 6 角色 Subagent + 单次委派」升级为**配置化、可独立运行、可互相通信的多 Agent 体系**。核心动作：

1. Agent 定义从 Python 类改为**配置文件**（`workspace/agents/<id>/agent.md`，沿用 Skill 的 frontmatter 惯例）
2. 每个 Agent 绑定**独立的 ProviderInstance + 模型**（复用现有 instance 体系，不复制凭据）
3. 每个 Agent 拥有**独立 skill 子集**（Skill 增加 `agents` 维度）
4. 每个 Agent 可声明**独立进程**（`isolation: process`，子进程 worker + JSONL 协议）
5. Agent 之间通过**通信工具**（`agent_ask` / `agent_notify`）经 MessageBroker 交互
6. Agent 间的**职责关系**由拓扑配置约束（谁能委派谁、谁能问谁、环路与跳数守卫）

| 需求 | 现状 | 改造后 |
|------|------|--------|
| 独立配置模型 | 仅 model 名覆盖，instance 跟随主对话 | `model.provider_instance` + `model.model` + 采样参数，per-agent 解析 |
| 独立职责 prompt | 6 个角色 prompt 硬编码在 `subagent.py` | agent.md 正文即 system prompt，文件+DB 双轨管理 |
| 独立进程 | 全部跑在主进程 asyncio 内 | `isolation: inline \| process`，process 模式独立解释器进程 + 独立沙箱目录 |
| 独立 skill 集合 | 仅全局 active_groups，subagent 无 skill | Skill 增加 `agents` 字段，per-agent 注入 |
| 可配置职责关系 | 仅 per-call 的 mode（sequential/parallel/map_reduce） | `topology.yaml` 声明 delegate/ask/notify 边，运行时守卫 |
| 通信 tool | 禁止嵌套，只回注主对话 | `agent_ask`（请求-应答）/ `agent_notify`（单向），broker 路由 + 跳数/环路守卫 |

---

## 1. 现状盘点（代码级证据）

### 1.1 已具备的资产（改造的起点，全部复用）

| 资产 | 位置 | 说明 |
|------|------|------|
| ProviderInstance 体系 | `jarvis/services/ai/instance_config.py` + `api/providers.py` | 多实例 CRUD、SQLite 持久化（`memory_store.save_setting`）、`AIRouter._get_client_with_instance()` 已支持 instance+model 粒度的客户端缓存 |
| Subagent 框架 | `jarvis/core/subagent.py` | `BaseSubagent`（含独立工具循环）、`SubagentConfig`（model/allowed_tools/temperature/timeout）、`SubagentOrchestrator`（sequential/parallel/map_reduce） |
| 独立子会话 | `Conversation(parent_conversation_id, session_kind="subagent", subagent_role, ...)` | v3 已落地：sub_session_id 可跳转，`message_store.save_sub_session()` 持久化，前端 `SubagentSessionPanel.vue` 已存在 |
| SkillStore | `jarvis/services/skill_store.py` | 文件 + DB 双轨、tags/groups、enabled 过滤、`get_enabled_for_active_groups()` 注入 system prompt |
| 工具白名单 | `SubagentConfig.allowed_tools` | 执行期拦截已实现（`BaseSubagent.run()` 内） |
| Agent Loop | `jarvis/core/agent_loop.py` | `AgentLoopRunner`：assistant turn 修复、去重、并行工具、iteration hint —— 但仅主对话三入口使用 |
| LLM 调用追溯 | `call_logger` + `conversation_id` 关联 | 天然可扩展 agent 维度 |
| TaskExecutor 策略集 | `jarvis/core/task_engine.py` | file/bash/browser/desktop/api/tool/subagent，`register_subagent()` 接线 |

### 1.2 六项差距（逐条对需求）

**① 模型配置不独立。** `BaseSubagent.__init__` 里 `self.instance = instance`——instance 由 `SubagentOrchestrator` 从 ChatEngine 逐会话注入（跟随主对话）；`SubagentConfig.model` 只是模型名字符串覆盖（`run()` 里 `model = self.config.model or self.main_model`）。无法做到「researcher 走云端 GPT、coder 走本地 qwen3:8b」。

**② 职责 prompt 硬编码。** `_ROLE_REGISTRY` 是 `dict[SubagentRole, type[BaseSubagent]]`，6 个角色的 prompt 写死在 `build_system_prompt()`。新增角色 = 改 Python 代码 + 发版。

**③ 无进程隔离。** `main.py` 单 FastAPI 进程，全局单例 `mediator = JarvisMediator()`，subagent 是同一 asyncio loop 里的协程：bash 卡死阻塞事件循环、pyautogui 崩溃带崩整个后端、所有 agent 共享一个 `TaskExecutor` 和同一个 `work_folder`。

**④ Skill 不区分 agent。** `SkillStore.get_enabled_for_active_groups()` 只有全局一组 active_groups，且只在 `ChatEngine._build_system_prompt()` 注入——subagent 的 `build_system_prompt()` 完全没有 skill 注入。

**⑤ 无职责关系配置。** 唯一的「关系」是调用时传的 `mode`（编排顺序），不是「谁可以委派谁 / 谁向谁汇报」的静态关系；`tool_registry` 里 `subagent` 工具的 `role` 是自由枚举，无约束校验。

**⑥ 无通信。** `BaseSubagent.run()` 里显式拦截：`if tool_name == "subagent": blocked("子代理内禁止嵌套调用 subagent")`——一刀切禁令替代了拓扑守卫；agent 之间没有任何消息通道。

### 1.3 顺带发现（本方案范围内修正，范围外仅记录）

- `BaseSubagent.run()` 内嵌一套独立的工具循环，未复用 `AgentLoopRunner`（`agent_loop.py` 的 docstring 说明它只为三个 chat 入口提取）。改造时统一，消除两份循环逻辑的漂移风险。
- `BashOperationStrategy.DANGEROUS_COMMANDS` 黑名单较弱（如拼写 `shitdown`、可绕过的管道写法）。进程隔离天然缩小爆炸半径，但黑名单强化**不在本方案范围**，仅记录。

---

## 2. 目标架构总览

```
┌────────────────────────────────────────────────────────────────────────┐
│ 主进程 (FastAPI :9529)                                                  │
│                                                                        │
│  ChatEngine (主对话, 虚拟节点 main)                                      │
│      │  delegate / agent_ask / agent_notify (工具调用)                  │
│      ▼                                                                 │
│  AgentOrchestrator v2                                                  │
│      ├── AgentRegistry ── 读 workspace/agents/<id>/agent.md (+DB 元数据) │
│      ├── TopologyGraph ── workspace/agents/topology.yaml (边校验/守卫)   │
│      ├── MessageBroker ── 邮箱 + 路由 + 跳数/环路守卫                    │
│      ├── InlineRuntime  ── asyncio 协程 (isolation: inline)             │
│      └── ProcessRuntime ── spawn 子进程 (isolation: process)            │
│              │  stdout JSONL 事件流 / stdin 控制指令                     │
│              ▼                                                         │
├────────────────────────────────────────────────────────────────────────┤
│ Worker 子进程 ×N   python -m jarvis.agent.worker --agent-id <id>        │
│   ├── 独立 AIRouter (绑定该 agent 的 ProviderInstance)                   │
│   ├── 独立 TaskExecutor (沙箱目录 workspace/agents/<id>/home)           │
│   ├── 独立 AgentLoop (复用 AgentLoopRunner)                             │
│   └── 该 agent 的 skill 子集注入 system prompt                           │
└────────────────────────────────────────────────────────────────────────┘
```

不变式：

- **主进程永远不被 agent 内的同步/崩溃拖死**——process 模式的 agent 挂了只丢该次任务。
- **凭据单一事实源**——agent 定义只引用 `provider_instance: <id>`，不复制 api_key。
- **守卫在 broker，不在 prompt**——「谁能联系谁」由 TopologyGraph 在执行层强制，LLM 想绕过也绕不过。

---

## 3. 核心设计

### 3.1 AgentDefinition —— 配置化代理定义

新增 `jarvis/core/agents/definition.py`。定义文件沿用 Skill 惯例（frontmatter + markdown 正文），正文即职责 prompt：

```markdown
# workspace/agents/coder/agent.md
---
id: coder
name: 编码工程师
description: 代码生成、修改与测试执行
model:
  provider_instance: ollama-default    # 引用 ProviderInstance.id（必填）
  model: qwen3:8b                      # 覆盖 instance.default_model（可选）
  temperature: 0.2
  max_tokens: 4096
tools: [file, bash, agent_ask, agent_notify]   # 空 = 继承全局工具集
skills: [python-best-practices, testing-guide] # 显式 skill id 列表；或 skills_groups
isolation: process                     # inline | process
sandbox: workspace/agents/coder/home   # process 模式下的独立工作目录
limits:
  max_iterations: 12
  timeout_s: 300
---
你是一名严谨的软件工程师。你只负责「编码工程师」职责范围内的工作：
- 接收明确的技术任务，产出可运行代码
- 修改代码前必须先读取目标文件
- 不做方案评审（那是 reviewer 的职责），不自行扩散任务范围
- 完成后报告变更的文件路径与验证结果
```

```python
# jarvis/core/agents/definition.py（关键签名）
@dataclass
class AgentModelBinding:
    provider_instance: str          # ProviderInstance.id
    model: Optional[str] = None     # None → 用 instance.default_model
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

@dataclass
class AgentDefinition:
    id: str
    name: str
    description: str
    system_prompt: str              # agent.md 正文
    model: AgentModelBinding
    tools: list[str]                # 空 = 全局默认集
    skills: list[str]               # skill id；另支持 skills_groups
    isolation: str = "inline"       # "inline" | "process"
    sandbox: Optional[str] = None
    limits: AgentLimits = ...
    enabled: bool = True            # DB 元数据（同 Skill）

    def resolve_instance(self) -> ProviderInstance:
        """从 InstanceConfigStore 解析绑定的实例；不存在/禁用时返回错误而非静默回退。"""
```

`AgentStore`（`registry.py`）完全镜像 `SkillStore` 模式：文件为内容源 + `memory_store.save_setting("agents_v1")` 存 `enabled`/模型绑定覆盖等元数据 + 启动/refresh 双向对账（磁盘有 DB 无 → 入库；磁盘无 DB 有 → 标 missing）。**内置 6 角色降级为 6 个种子 agent.md**，首次启动 seed，用户可直接编辑。

> 兼容：`SubagentRole` 枚举保留为别名映射（`researcher → agent:researcher`），`subagent` 工具的 `role` 参数继续可用，现有测试与 prompt 习惯不受影响。

### 3.2 模型绑定 —— per-agent 独立模型

改动集中在编排器构造 agent 的路径：

- 现状：`ChatEngine.__init__` 创建唯一 `SubagentOrchestrator`，`instance`/`model` 逐会话整体注入。
- 改造后：`AgentOrchestrator.dispatch()` 按 `AgentDefinition.model` **逐 agent** 解析：

```python
inst = definition.resolve_instance()            # 各自的 ProviderInstance
model = definition.model.model or inst.default_model
client = router._get_client_with_instance(inst, model)   # 现成机制，缓存键已含 instance.id
```

`AIRouter._get_client_with_instance()` 与调用日志（`call_logger`）**零改动**即支持——这正是复用 instance 体系的原因。模型解析失败（实例被删/禁用）返回结构化错误给委派方，**不静默回退主对话模型**（静默回退会掩盖配置问题）。

### 3.3 Skill 集合 —— per-agent 过滤

`Skill` dataclass 增加一个字段：

```python
agents: list[str] = field(default_factory=list)   # 空 = 全局（主对话 + 任何 agent 可见）
```

过滤语义与现有 groups 正交叠加：

```python
# SkillStore 新增
def get_enabled_for_agent(self, agent_id: str) -> list[Skill]:
    """enabled AND not missing AND (agents 为空 OR agent_id ∈ agents)"""
```

注入点：agent 运行时构建 system prompt 时，`## 可用技能` 段落与主对话同格式注入。前端 `SkillManager.vue` 的编辑 modal 增加「可见 Agent」多选；`AgentManager.vue` 反向提供 skill 多选。存量 skill 的 `agents=[]`，行为完全不变。

### 3.4 工具集合与沙箱

- **可见性双层**：schema 层（发给 LLM 的 `tools` 只含该 agent 的 `tools` 列表，弱模型少走弯路）+ 执行层（沿用 `allowed_tools` 拦截机制，作为不可绕过的强制层）。
- **沙箱**：process 模式 agent 的 `TaskExecutor(work_folder=definition.sandbox)`——bash/file 默认相对路径全部落在自己目录内；inline 模式沿用全局 workspace（同进程，只能做到目录隔离，见 §6 权衡表）。

### 3.5 进程模型 —— 两级隔离 + Worker 协议

`isolation` 是 per-agent 声明，两种运行时实现同一个接口：

```python
class AgentRuntime(ABC):
    async def dispatch(self, task: AgentTask) -> AsyncIterator[AgentEvent]: ...
    async def ask(self, question: str, *, from_id: str, timeout: float) -> str: ...
    async def cancel(self) -> None: ...
    def status(self) -> RuntimeStatus: ...   # inline: idle/running; process: + pid/mem/restarts
```

**InlineRuntime**：现有 `BaseSubagent.run()` 迁移到 `AgentLoopRunner`（消除双循环），协程内执行。

**ProcessRuntime**：`asyncio.create_subprocess_exec` 启动 worker：

```bash
venv/bin/python -m jarvis.agent.worker --agent-id coder --runtime-id <uuid>
```

**JSONL 协议**（stdout 事件 / stdin 控制）：

```
stdout → {"type":"ready","agent":"coder","pid":1234}
         {"type":"token","delta":"..."}                      # 可选流式
         {"type":"tool_call","tool":"bash","params":{...}}
         {"type":"tool_result","tool":"bash","status":"success","result":"..."}
         {"type":"ask_out","correlation_id":"...","to":"reviewer","content":"..."}   # 转发 agent_ask
         {"type":"done","result":{...SubagentResult 兼容字段...}}
         {"type":"error","message":"...","fatal":true}
stdin  ← {"type":"ask_in","correlation_id":"...","content":"..."}     # broker 送回的答案
         {"type":"notify","from":"planner","content":"..."}           # 邮箱投递
         {"type":"cancel"}
```

Worker 进程内（`jarvis/agent/worker.py`）：加载 AgentDefinition → 构建独立 `AIRouter`（绑定 instance）→ 独立 `TaskExecutor`（沙箱目录）→ 复用 `AgentLoopRunner` 跑循环 → 事件打印到 stdout。父进程 `ProcessRuntime` 解析事件：`tool_call/tool_result` 转发为现有 SSE 事件（**前端零改动**），`ask_out` 交给 broker，`done` 汇总为结果。

生命周期策略：超时（`limits.timeout_s`）→ SIGTERM → 宽限 5s → SIGKILL；`ready` 超时 10s 判启动失败；连续崩溃 3 次熔断该 agent（下次 dispatch 直接报错，UI 标红），可配置 `restart: always`。

### 3.6 通信机制 —— MessageBroker + 两个通信工具

新增 `jarvis/core/agents/broker.py`。每个 agent（含主对话 `main`）一个邮箱地址 `agent://<id>`：

```python
class MessageBroker:
    async def ask(self, from_id, to_id, content, *, timeout, hop_context) -> "AskReply"
    async def notify(self, from_id, to_id, content, hop_context) -> None
```

**两个 LLM 工具**（注册进 `ToolRegistry`，schema 从简，弱模型可用）：

```python
ToolDefinition(name="agent_ask", 
    description="向另一个 agent 提问并等待回答（请求-应答，带超时）",
    parameters={"to": "目标 agent id", "content": "问题/请求", "timeout_s": "可选超时(默认60)"})

ToolDefinition(name="agent_notify",
    description="向另一个 agent 发送单向消息，不等待回答",
    parameters={"to": "目标 agent id", "content": "消息内容"})
```

路由与投递规则：

- `agent_ask`：目标 agent 正在运行 → 在其当前循环注入一次 `[来自 coder 的询问] ...`（作为 user turn），应答在有限轮内产出后按 `correlation_id` 送回；目标空闲 → 现场拉起一次轻量 dispatch（prompt = 消息内容），应答即结果。`from_id` 与 `hop_context` 由运行时注入，**LLM 无法伪造**。
- `agent_notify`：投递到目标邮箱；目标运行中 → 下一轮注入；空闲 → 持久化到其会话（复用 `save_sub_session`），下次运行时作为开场上文。
- **主对话也是节点**（`main`）：subagent 结果回注主对话即 `notify(main)` 的特例，现有「结果回注」路径不变。

**守卫（替代一刀切禁令）**：

- `hop_context`：每次顶层 dispatch 生成 trace，`ask/notify/delegate` 都携带并 +1；`max_hops`（默认 3，per-agent 可覆盖）超限拒绝。
- 环路检测：同一 trace 内 `(from,to)` 重复出现即拒绝（A↔B 互问死循环）。
- 超时层层设防：单次 ask 有 timeout，agent 整体有 `limits.timeout_s`。

### 3.7 职责拓扑 —— 可配置关系

新增 `workspace/agents/topology.yaml`：

```yaml
# 节点：main + 所有 agent id（自动推导，无需声明）
edges:
  - from: main
    to: [planner, researcher, coder]
    relation: delegate          # 可委派任务（subagent/delegate 工具）
  - from: coder
    to: [reviewer]
    relation: ask               # 可请求-应答（如让 reviewer 判一段改动）
  - from: reviewer
    to: [coder]
    relation: notify            # 只能单向回告（reviewer 不许反过来派活）
  - from: planner
    to: [coder, researcher]
    relation: delegate
policies:
  max_hops: 3
  default_relation: deny        # 未声明的边默认拒绝（白名单模式）
```

- `TopologyGraph.validate(from, to, action)` 在 broker 与 orchestrator 的 dispatch 前强制校验；校验失败返回结构化错误（LLM 能读到「无权联系该 agent」并自行调整）。
- 关系是**约束**不是**编排脚本**：执行顺序仍由 `mode`（sequential/parallel/map_reduce，保留）决定；拓扑只回答「允许谁联系谁」。流水线类协作（coder 产出自动送 reviewer）通过 planner/主对话的 `delegate(mode=sequential)` 表达，不引入隐式自动触发（隐式触发难调试，明确拒绝——见 §6）。
- 三个内置模板一键生成：`supervisor`（main→全员 delegate）、`pipeline`（A→B delegate + B→A notify）、`solo`（无内部边）。

### 3.8 会话与可观测性

- **会话**：沿用 v3 子会话——`Conversation(session_kind="agent", subagent_role=agent_id, ...)`，`SubagentSessionPanel.vue` 扩展为 AgentSessionPanel（按 agent 分组 + 通信事件渲染 `💬 ask/notify` 条目）。
- **LLM 日志**：`call_logger` 已有 `conversation_id`；新增 `agent_id` 字段（dispatch 时注入 adapter kwargs），按会话视图即可看「一次委派触发的、跨多个 agent 的调用链」。
- **运行时状态**：`GET /api/agents/runtime` 返回每个 agent 的 isolation/pid/内存/重启次数/当前任务，前端 Header 加状态点。

---

## 4. 数据模型与接口汇总

### 4.1 新增文件

```
jarvis/core/agents/
├── __init__.py
├── definition.py      # AgentDefinition / AgentModelBinding / AgentLimits + 解析校验
├── registry.py        # AgentStore（文件+DB 双轨，镜像 SkillStore）
├── topology.py        # TopologyGraph（边校验/环路/hops）
├── broker.py          # MessageBroker（邮箱/路由/守卫）
├── runtime.py         # AgentRuntime ABC + InlineRuntime
├── process_runtime.py # ProcessRuntime（子进程宿主）
└── orchestrator.py    # AgentOrchestrator v2（调度/生命周期/SSE 事件）
jarvis/agent/
├── __init__.py
├── worker.py          # 子进程入口（python -m jarvis.agent.worker）
└── bootstrap.py       # worker 内组装 router/executor/loop/skills
jarvis/api/agents.py   # Agent CRUD + 拓扑 + 运行时状态端点
tests/
├── test_agent_registry.py
├── test_agent_topology.py
├── test_agent_broker.py
├── test_agent_model_binding.py
└── test_agent_worker.py      # 进程协议测试（标 slow）
```

### 4.2 API 端点（`jarvis/api/agents.py`，镜像 `/api/providers` 风格）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents` | 列表（含 DB 元数据 + 模型绑定解析结果） |
| GET/POST/PUT/DELETE | `/api/agents/{id}` | 定义 CRUD（写 agent.md + DB） |
| PATCH | `/api/agents/{id}/toggle` | 启停 |
| POST | `/api/agents/refresh` | 从磁盘对账（镜像 skills/refresh） |
| GET/PUT | `/api/agents/topology` | 拓扑读写 + 校验报告（孤立节点/缺目标） |
| GET | `/api/agents/runtime` | 运行时状态（inline/process、pid、重启数） |
| POST | `/api/agents/{id}/test` | 干跑一条测试任务（冒烟） |

### 4.3 工具层变更（`tool_registry.py`）

- 新增 `agent_ask`、`agent_notify`（§3.6）。
- `subagent` 工具保留原名与参数，新增可选 `agent_id` 参数；`role` 与 `agent_id` 二选一，内部统一解析为 agent id，经 TopologyGraph 校验。

---

## 5. 分阶段实施计划

> 每个 PR 独立可合、可回滚；合并前跑 `python -m pytest tests/ -v`（基线见附录 A，4 个既有失败不得新增）。文件级清单只为关键改动，非穷举。

### 阶段 A：配置化定义 + 模型/Skill 绑定（全 inline，行为兼容）

**PR-A1 AgentDefinition + AgentStore**
- 新增 `core/agents/definition.py`、`registry.py`；6 内置角色 seed 为 `workspace/agents/*/agent.md`
- 改 `subagent.py`：`_ROLE_REGISTRY` 查找改为「先 AgentStore 后内置类」
- 测试：`test_agent_registry.py`（镜像 test_skill_store 的覆盖密度：seed/CRUD/toggle/refresh/missing）
- 验收：不配置任何 agent.md 时，现有 `test_subagent.py` 全绿（别名兼容）

**PR-A2 per-agent 模型绑定**
- `AgentOrchestrator.dispatch()` 逐 agent 解析 instance/model；`resolve_instance()` 失败显式报错
- 测试：`test_agent_model_binding.py`（多 agent 不同实例、实例禁用、模型覆盖优先级）
- 验收：两个 agent 分别绑定不同 ProviderInstance，LLM 日志中 provider 字段各自正确

**PR-A3 per-agent Skill**
- `Skill.agents` 字段 + `get_enabled_for_agent()` + `SkillManager.vue` 多选
- agent system prompt 注入 `## 可用技能`
- 测试：skill 过滤正反用例（agents 空/含/不含、enabled、missing）
- 验收：存量 skill 行为零变化（回归 `test_skill_store.py` 全绿）

### 阶段 B：通信与拓扑（inline 打通，进程无关）

**PR-B1 MessageBroker + 通信工具**
- 新增 `broker.py`、`agent_ask`/`agent_notify` 工具、hop_context
- 邮箱投递语义（运行中注入下一轮 / 空闲持久化）
- 测试：`test_agent_broker.py`（fake runtime：路由、correlation 配对、超时、hops 超限、环路拒绝）
- 验收：两个 inline agent 完成 ask 往返，主对话 SSE 可见通信事件

**PR-B2 TopologyGraph**
- 新增 `topology.py`、`topology.yaml` 读写、三个模板
- broker + orchestrator 双侧校验；`default_relation: deny`
- 测试：`test_agent_topology.py`（白名单/环路/hops/未声明边拒绝/模板生成）
- 验收：越权 delegate 返回结构化拒绝，合法链路正常

### 阶段 C：进程隔离

**PR-C1 Worker 运行时**
- 新增 `agent/worker.py`、`bootstrap.py`、`process_runtime.py`；JSONL 协议解析
- Worker 内复用 `AgentLoopRunner`（顺手完成 §1.3 的循环统一——`BaseSubagent.run()` 迁移）
- 测试：`test_agent_worker.py`（ready/done/tool 事件解析、ask_out 往返、stdin cancel；进程测试标 `@pytest.mark.slow`）
- 验收：`isolation: process` 的 agent 完成 bash 工具任务；杀掉 worker 主进程存活

**PR-C2 生命周期管理**
- 超时/SIGTERM/SIGKILL 阶梯、连续崩溃熔断、`restart` 策略、`/api/agents/runtime`
- 测试：超时回收、崩溃计数、熔断后再恢复
- 验收：`pkill -9 -f "jarvis.agent.worker"` 后主服务 5s 内感知并按策略恢复

### 阶段 D：前端

**PR-D AgentManager + 会话/状态扩展**
- `AgentManager.vue`（镜像 ProviderManager）：定义编辑、模型绑定下拉（数据源 `/api/providers`）、skills/tools 多选、isolation 开关
- `SubagentSessionPanel.vue` → 通信事件渲染；Header 运行时状态点
- 验收：`cd frontend && npm run build` 通过；手动 E2E：建 agent → 配模型 → 拓扑 → 派任务 → 看子会话

### 阶段 E：可观测性收尾

**PR-E agent 维度追溯**
- `call_logger` 加 `agent_id`；按会话视图聚合跨 agent 调用链；per-agent token 汇总
- 验收：一次多 agent 协作在 LLM 日志会话视图里呈完整链路

### 迁移与回滚

- 配置迁移：无（AgentStore 首启 seed，存量 subagent 调用走别名）
- 回滚：每 PR 独立；阶段 C 回滚 = agent.md 里 `isolation` 改回 `inline`，无需回滚代码即可降级运行
- 预估量级：A≈3 个 PR 中等，B≈2 个 PR 中等，C≈2 个 PR 较重（进程调试），D/E 中等

---

## 6. 风险与权衡

| 决策 | 取舍 | 理由 |
|------|------|------|
| 默认 inline、process 可选 | 不强制每 agent 一进程 | 本地桌面形态：Ollama 本身共享、进程冷启动 ~0.5-1s + 每个 worker 独立 Python 解释器内存；危险工具型 agent（bash/desktop）才值得付这个成本。需求「可独立进程」满足为**能力**而非默认 |
| 模型绑定引用 instance id | 不在 agent.md 里复制 api_key | 凭据单一事实源；换 key 一处生效；避免明文 key 散落 workspace（可被 file 工具读到） |
| 通信只给 ask/notify 两个工具 | 不做任意消息原语 | 弱本地模型（qwen3:4b）工具选择能力有限，两个语义清晰的工具比一个万能 `send` 可靠 |
| 拓扑白名单 + 执行层强制 | 不做 prompt 约定、不做隐式自动流转 | prompt 约定可被绕过；隐式触发（A 产出自动送 B）调试成本高，让主对话/planner 显式编排 |
| 双循环统一到 AgentLoopRunner | 一次性迁移放在 PR-C1 | 风险集中在 worker 复用处；单独迁移会引入纯重构 PR，合并进 C1 有真实测试兜底 |
| 邮箱空闲持久化复用子会话 | 不新建存储模型 | v3 子会话基建已落地，少一张表 |

主要风险与对策：

1. **本地 Ollama 并发瓶颈**——多 agent 并行请求同一 Ollama 会排队拖长延迟。对策：per-agent instance 可指向不同端点/云端；编排器支持 `concurrency` 限额（阶段 B 顺手加）。
2. **弱模型滥用通信工具**——互问死循环。对策：hops/环路双守卫 + iteration hint（AgentLoopRunner 已有）。
3. **进程协议的边界 case**（stdout 缓冲、半行 JSON、崩溃前未发 done）。对策：worker 内 `sys.stdout = LineBufferedWriter`，父进程按行解析容错半行；心跳事件（每 30s）检测僵死。
4. **配置漂移**（agent.md 手改后 DB 元数据过期）。对策：完全照搬 SkillStore 的 refresh 对账机制，已被验证。

---

## 7. 附录

### A. 测试基线（2026-09-30，改造前）

```
$ venv/bin/python -m pytest tests/ -q
4 failed, 275 passed, 8 warnings in 20.74s

FAILED tests/test_context_compressor.py::TestCooldown::test_cooldown_blocks_repeat      # 既有失败
FAILED tests/test_context_compressor.py::TestCooldown::test_cooldown_expires            # 既有失败
FAILED tests/test_context_compressor.py::TestStats::test_compress_count_increments      # 既有失败
FAILED tests/test_context_manager.py::TestSlidingWindow::test_respects_token_budget     # 既有失败
```

判定依据：本次方案输出未改动任何代码，上述 4 项在动手前基线中即失败，与多 Agent 改造无关联。实施各 PR 时以「不新增失败」为门槛，这 4 项按既有失败单独跟踪，不顺手修改（避免扩大改动面）。

### B. 与既有方案文档的关系

- `subagent独立会话方案.md`（v3）：**子会话部分已落地**（`Conversation.session_kind="subagent"`、`sub_session_id` 跳转、`SubagentSessionPanel.vue` 均已在代码中验证存在）。本方案直接复用该基建，session_kind 扩展 `"agent"`。
- `agent_loop_review_0828.md` / `agent-toolcall-paradigm.md`：AgentLoopRunner 的既有评审结论（assistant turn 修复、hint 机制）被本方案全盘继承，worker 进程内即复用该 Runner。
- `CLAUDE.md` 的 Common Pitfalls 中「SubagentConfig 必填 system_prompt」在配置化后由 agent.md 正文保证；「新增模型双写」提示本方案不触碰（per-agent 只选既有 instance/model）。

---

*方案完。实施从 PR-A1 开始，每 PR 独立评审、独立回滚。*
