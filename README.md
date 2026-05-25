# 贾维斯（JARVIS）系统初始化说明书

## 系统概述

贾维斯是基于 Claude Code 的智能助手系统，支持完整的多模态交互能力。

## 核心能力

| 能力 | 说明 | 触发方式 |
|------|------|----------|
| **听** | 语音识别与理解 | 用户语音输入 |
| **说** | 语音合成与播报 | 调用 `speak` 技能 |
| **读** | 文件/图片/PDF读取 | 使用 `Read` 工具读取文件 |
| **写** | 代码/文档生成 | `Write`/`Edit` 工具创建或编辑文件 |
| **执行** | 调用任意工具 | 工具面板中的所有 MCP 工具 |

## 可用工具分类

### 1. 文件操作
- **Read** - 读取本地文件内容
- **Write** - 创建或覆盖文件
- **Edit** - 修改文件局部内容
- **Glob** - 按模式搜索文件

### 2. AI 能力
- **Agent** - 并行任务处理、深度研究
- ** tavily-search** - 网络搜索
- ** summarize** - 总结 URL/PDF/图片

### 3. 终端操作
- **Bash** - 执行 Shell 命令
- **WebFetch** - 获取网页内容

### 4. 浏览器自动化
- **playwright-cli** / **agent-browser** - 网页交互与测试
- **opencli-skill** - 任意网站 CLI 化

### 5. 系统控制
- **desktop-control** - 高级桌面自动化（鼠标、键盘、屏幕控制）
- **computer_batch** - 批量计算机操作

### 6. 内容生成
- **ollama-t2i** - 本地文生图（x/z-image-turbo 1024x1024）
- **ollama-vision** - 本地图片理解（qwen3-vl:4b）
- **ppt-generator** - 乔布斯风竖屏 HTML 演示稿
- **algorithmic-art** - p5.js 算法艺术
- **plantuml-render** - PlantUML 图表渲染

### 7. 文档处理
- **pdf** / **pptx** / **docx** / **xlsx** - 各类型文档读写
- **markdown** - 文档编写

### 8. 专业化写作
- **scientific-writing** - 学术论文写作
- **nature-writing** / **nature-polishing** - Nature 风格润色
- **paper-workflow** - 稿件工作流
- **internal-comms** - 企业内部通讯

### 9. 代码开发
- **coding** - 编码风格与最佳实践
- **vibe-coding** / **vibe-dev** - AI 辅助开发
- **frontend-design** - 前端界面设计
- **webapp-testing** - Web 应用测试

## 技能（Skills）使用

技能需通过 `Skill` 工具调用：

```
技能名: "pdf"
参数: 文件路径或任务描述
```

常用技能速查：
- `pdf` - PDF 读取、提取、合并
- `xlsx` - Excel 表格处理
- `docx` - Word 文档编辑
- `pptx` - PowerPoint 演示文稿
- `code` - 代码开发工作流
- `speak` / `tts` - 语音合成播放
- `save-image` - 保存图片到工作区
- `tavily-search` - AI 网络搜索

## 技能创建与扩展

如需创建自定义技能：
1. 使用 `skill-creator` 技能获取指导
2. 使用 `mcp-builder` 构建 MCP 服务器

## 记忆系统

贾维斯具备持久化记忆能力：

| 类型 | 路径 | 用途 |
|------|------|------|
| **user** | `/memory/user_*.md` | 用户角色、偏好、知识 |
| **feedback** | `/memory/feedback_*.md` | 用户反馈与纠正 |
| **project** | `/memory/project_*.md` | 项目上下文与目标 |
| **reference** | `/memory/reference_*.md` | 外部系统引用指针 |

记忆文件使用 YAML frontmatter 格式，通过 `MEMORY.md` 索引。

## 系统状态

- **当前目录**: `/Users/jiafei/claude/Jarvis_demo`
- **日期**: 2026-05-25
- **模型**: MiniMax-M2.7 / Claude 4.5/4.6 系列

## 快速开始

1. **提问** - 直接输入问题或任务描述
2. **执行** - 说"执行"、"run"触发 Bash 命令
3. **创建** - 说"写代码"、"生成PPT"触发对应技能
4. **记忆** - 说"记住..."让贾维斯保存信息

---
*贾维斯系统初始化完成，随时待命。*