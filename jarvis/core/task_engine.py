# jarvis/core/task_engine.py
"""任务执行引擎 - Strategy Pattern + Mediator Pattern"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from jarvis.core.entities import Task, Step, TaskStatus
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class TaskStrategy(ABC):
    """任务策略抽象基类（Strategy Pattern）"""

    @abstractmethod
    async def execute(self, step: Step) -> Any:
        """执行任务步骤"""
        pass


class BrowserAutomationStrategy(TaskStrategy):
    """浏览器自动化策略"""

    async def execute(self, step: Step) -> Any:
        """使用 Playwright 执行浏览器任务"""
        logger.info(f"Browser automation: {step.tool} with {step.params}")
        try:
            from playwright.async_api import async_playwright

            params = step.params
            action = params.get("action", "navigate")
            url = params.get("url", "")

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                if action == "navigate" and url:
                    await page.goto(url)
                    result = f"Navigated to {url}"
                elif action == "click":
                    selector = params.get("selector")
                    if selector:
                        await page.click(selector)
                        result = f"Clicked {selector}"
                    else:
                        result = "No selector provided"
                elif action == "type":
                    selector = params.get("selector")
                    text = params.get("text", "")
                    if selector:
                        await page.fill(selector, text)
                        result = f"Typed '{text}' into {selector}"
                    else:
                        result = "No selector provided"
                else:
                    result = f"Action {action} not implemented"

                await browser.close()
                return {"status": "success", "result": result}
        except ImportError:
            logger.warning("Playwright not installed, returning simulated result")
            return {"status": "simulated", "tool": step.tool, "params": step.params}
        except Exception as e:
            logger.error(f"Browser automation error: {e}")
            return {"status": "error", "message": str(e)}


class DesktopControlStrategy(TaskStrategy):
    """桌面控制策略"""

    async def execute(self, step: Step) -> Any:
        """使用 pyautogui 执行桌面任务"""
        logger.info(f"Desktop control: {step.tool} with {step.params}")
        try:
            import pyautogui

            params = step.params
            action = params.get("action", "")

            if action == "click":
                x = params.get("x", 0)
                y = params.get("y", 0)
                pyautogui.click(x, y)
                result = f"Clicked at ({x}, {y})"
            elif action == "move":
                x = params.get("x", 0)
                y = params.get("y", 0)
                pyautogui.moveTo(x, y)
                result = f"Moved to ({x}, {y})"
            elif action == "type":
                text = params.get("text", "")
                pyautogui.typewrite(text)
                result = f"Typed '{text}'"
            elif action == "press":
                key = params.get("key", "")
                pyautogui.press(key)
                result = f"Pressed '{key}'"
            else:
                result = f"Action {action} not implemented"

            return {"status": "success", "result": result}
        except ImportError:
            logger.warning("pyautogui not installed, returning simulated result")
            return {"status": "simulated", "tool": step.tool, "params": step.params}
        except Exception as e:
            logger.error(f"Desktop control error: {e}")
            return {"status": "error", "message": str(e)}


class APICallStrategy(TaskStrategy):
    """API 调用策略"""

    async def execute(self, step: Step) -> Any:
        """调用外部 API"""
        import httpx
        logger.info(f"API call: {step.tool}")

        params = step.params
        if "url" in params:
            method = params.get("method", "GET")
            headers = params.get("headers", {})
            json_data = params.get("body", {})

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method, params["url"], headers=headers, json=json_data
                )
            return {"status": "success", "data": response.json()}
        return {"status": "error", "message": "No URL provided"}


class FileOperationStrategy(TaskStrategy):
    """文件操作策略 - 读、写、改、删"""

    def __init__(self, work_folder: Optional[str] = None):
        self.work_folder = work_folder or str(Path.cwd())

    def _resolve_path(self, path: str) -> Path:
        """解析文件路径，支持相对路径和绝对路径，防止路径穿越"""
        work = Path(self.work_folder).resolve()
        p = Path(path).resolve()

        # 路径穿越检测：确保解析后的路径在 work_folder 内
        try:
            p.relative_to(work)
        except ValueError:
            raise PermissionError(f"路径穿越禁止: {path} 不在工作目录内")

        return p

    async def execute(self, step: Step) -> Any:
        """执行文件操作"""
        import json
        logger.info(f"File operation: {step.tool} with {step.params}")

        params = step.params
        action = params.get("action", "")
        file_path = params.get("path", "")

        try:
            if action == "read":
                return await self._read_file(file_path)
            elif action == "write":
                content = params.get("content", "")
                return await self._write_file(file_path, content)
            elif action == "edit":
                old_content = params.get("old_content", "")
                new_content = params.get("new_content", "")
                return await self._edit_file(file_path, old_content, new_content)
            elif action == "delete":
                return await self._delete_file(file_path)
            elif action == "list":
                return await self._list_files(file_path)
            elif action == "mkdir":
                return await self._mkdir(file_path)
            elif action == "exists":
                return await self._file_exists(file_path)
            elif action == "set_work_folder":
                folder = params.get("folder", "")
                self.work_folder = folder
                return {"status": "success", "message": f"工作文件夹已设置为: {folder}"}
            elif action == "get_work_folder":
                return {"status": "success", "folder": self.work_folder}
            else:
                return {"status": "error", "message": f"未知操作: {action}"}
        except Exception as e:
            logger.error(f"File operation error: {e}")
            return {"status": "error", "message": str(e)}

    async def _read_file(self, path: str) -> dict:
        """读取文件"""
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return {"status": "error", "message": f"文件不存在: {path}"}
        if not full_path.is_file():
            return {"status": "error", "message": f"不是文件: {path}"}

        try:
            content = full_path.read_text(encoding="utf-8")
            return {
                "status": "success",
                "path": str(full_path),
                "content": content,
                "lines": len(content.splitlines())
            }
        except UnicodeDecodeError:
            content = full_path.read_bytes()
            import base64
            return {
                "status": "success",
                "path": str(full_path),
                "content": base64.b64encode(content).decode(),
                "encoding": "base64",
                "size": len(content)
            }

    async def _write_file(self, path: str, content: str) -> dict:
        """写入文件"""
        full_path = self._resolve_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, str) and content.startswith("base64:"):
            import base64
            data = base64.b64decode(content[7:])
            full_path.write_bytes(data)
        else:
            full_path.write_text(content, encoding="utf-8")

        return {
            "status": "success",
            "message": f"文件已写入: {path}",
            "path": str(full_path)
        }

    async def _edit_file(self, path: str, old_content: str, new_content: str) -> dict:
        """修改文件"""
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return {"status": "error", "message": f"文件不存在: {path}"}

        text = full_path.read_text(encoding="utf-8")
        if old_content not in text:
            return {"status": "error", "message": "未找到要替换的内容"}

        new_text = text.replace(old_content, new_content, 1)
        full_path.write_text(new_text, encoding="utf-8")

        return {
            "status": "success",
            "message": f"文件已修改: {path}",
            "path": str(full_path)
        }

    async def _delete_file(self, path: str) -> dict:
        """删除文件"""
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return {"status": "error", "message": f"文件不存在: {path}"}

        if full_path.is_file():
            full_path.unlink()
        elif full_path.is_dir():
            import shutil
            shutil.rmtree(full_path)

        return {
            "status": "success",
            "message": f"已删除: {path}",
            "path": str(full_path)
        }

    async def _list_files(self, path: str = "") -> dict:
        """列出目录文件"""
        full_path = self._resolve_path(path) if path else Path(self.work_folder)
        if not full_path.exists():
            return {"status": "error", "message": f"目录不存在: {path}"}
        if not full_path.is_dir():
            return {"status": "error", "message": f"不是目录: {path}"}

        files = []
        dirs = []
        for item in full_path.iterdir():
            if item.is_file():
                files.append({"name": item.name, "size": item.stat().st_size})
            elif item.is_dir():
                dirs.append(item.name)

        return {
            "status": "success",
            "path": str(full_path),
            "files": files,
            "directories": dirs
        }

    async def _mkdir(self, path: str) -> dict:
        """创建目录"""
        full_path = self._resolve_path(path)
        full_path.mkdir(parents=True, exist_ok=True)
        return {
            "status": "success",
            "message": f"目录已创建: {path}",
            "path": str(full_path)
        }

    async def _file_exists(self, path: str) -> dict:
        """检查文件是否存在"""
        full_path = self._resolve_path(path)
        return {
            "status": "success",
            "exists": full_path.exists(),
            "is_file": full_path.is_file() if full_path.exists() else None,
            "is_dir": full_path.is_dir() if full_path.exists() else None
        }


class ToolRunnerStrategy(TaskStrategy):
    """工具运行策略 - 运行 MCP 工具"""

    async def execute(self, step: Step) -> Any:
        """执行 MCP 工具"""
        logger.info(f"Running tool: {step.tool}")
        # TODO: 集成 Claude Code MCP
        return {"status": "simulated", "tool": step.tool, "params": step.params}


class TaskExecutor:
    """任务执行器 - 根据任务类型选择策略"""

    def __init__(self, work_folder: Optional[str] = None):
        self.file_strategy = FileOperationStrategy(work_folder)
        self.strategies: dict[str, TaskStrategy] = {
            "browser": BrowserAutomationStrategy(),
            "desktop": DesktopControlStrategy(),
            "api": APICallStrategy(),
            "tool": ToolRunnerStrategy(),
            "file": self.file_strategy,
        }
        logger.info("TaskExecutor initialized with strategies: "
                   f"{list(self.strategies.keys())}")

    def get_strategy(self, task_type: str) -> TaskStrategy:
        """获取策略"""
        strategy = self.strategies.get(task_type, ToolRunnerStrategy())
        logger.debug(f"Strategy for {task_type}: {type(strategy).__name__}")
        return strategy

    async def execute_step(self, step: Step) -> Any:
        """执行单个步骤"""
        strategy = self.get_strategy(step.tool)
        return await strategy.execute(step)


class TaskEngine:
    """任务执行引擎 - 负责任务分解和执行"""

    def __init__(self):
        self.executor = TaskExecutor()
        logger.info("TaskEngine initialized")

    async def execute_task(self, task_description: str) -> Task:
        """执行任务（单步简化为直接执行）"""
        task = Task(description=task_description)
        task.status = TaskStatus.RUNNING

        logger.info(f"Executing task: {task_description}")

        # 简化实现：创建单个步骤
        step = Step(tool="tool", params={"description": task_description})
        task.steps.append(step)

        try:
            result = await self.executor.execute_step(step)
            step.result = result
            task.status = TaskStatus.COMPLETED
            task.result = str(result)
            logger.info(f"Task completed: {task.task_id}")
        except Exception as e:
            logger.error(f"Task failed: {e}")
            task.status = TaskStatus.FAILED
            task.result = f"Error: {str(e)}"

        return task

    async def execute_steps(self, steps: list[Step]) -> list[Any]:
        """顺序执行多个步骤"""
        results = []
        for step in steps:
            logger.info(f"Executing step: {step.tool}")
            try:
                result = await self.executor.execute_step(step)
                step.result = result
                results.append(result)
            except Exception as e:
                logger.error(f"Step failed: {e}")
                step.result = {"error": str(e)}
                results.append(step.result)
        return results

    async def plan_steps(self, task_description: str) -> list[Step]:
        """LLM 分解任务为步骤"""
        try:
            from jarvis.services.ollama_client import ollama_client

            prompt = f"""将以下任务分解为可执行步骤，返回 JSON 数组格式：
任务: {task_description}

要求：
- 每个步骤包含 tool (工具类型: browser/desktop/api) 和 params (参数)
- 步骤应按顺序执行
- 返回格式示例: [{{"tool": "browser", "params": {{"action": "navigate", "url": "https://..."}}}}]

只返回 JSON 数组，不要其他内容。"""

            response = await ollama_client.generate(prompt, stream=False)

            import json
            import re

            # 尝试从响应中提取 JSON
            match = re.search(r'\[.*\]', response.content, re.DOTALL)
            if match:
                steps_data = json.loads(match.group())
                steps = [Step(tool=s.get("tool", "tool"), params=s.get("params", {})) for s in steps_data]
                return steps
            return []
        except Exception as e:
            logger.error(f"Task planning error: {e}")
            return []

    def to_dict(self) -> dict:
        """导出状态"""
        return {
            "executor_strategies": list(self.executor.strategies.keys())
        }