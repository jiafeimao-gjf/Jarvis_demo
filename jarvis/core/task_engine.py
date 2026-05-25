# jarvis/core/task_engine.py
"""任务执行引擎 - Strategy Pattern + Mediator Pattern"""
from abc import ABC, abstractmethod
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


class ToolRunnerStrategy(TaskStrategy):
    """工具运行策略 - 运行 MCP 工具"""

    async def execute(self, step: Step) -> Any:
        """执行 MCP 工具"""
        logger.info(f"Running tool: {step.tool}")
        # TODO: 集成 Claude Code MCP
        return {"status": "simulated", "tool": step.tool, "params": step.params}


class TaskExecutor:
    """任务执行器 - 根据任务类型选择策略"""

    def __init__(self):
        self.strategies: dict[str, TaskStrategy] = {
            "browser": BrowserAutomationStrategy(),
            "desktop": DesktopControlStrategy(),
            "api": APICallStrategy(),
            "tool": ToolRunnerStrategy(),
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
        strategy = self.get_strategy(step.tool.split(".")[0] if "." in step.tool else "tool")
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