# jarvis/api/execute.py
"""任务执行相关 API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from jarvis.core.mediator import mediator
from jarvis.core.entities import Step
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/execute", tags=["execute"])


class ExecuteRequest(BaseModel):
    """任务执行请求模型"""
    task: str
    steps: Optional[list[dict]] = None


class ExecuteResponse(BaseModel):
    """任务执行响应模型"""
    task_id: str
    status: str
    result: Optional[str] = None


@router.post("", response_model=ExecuteResponse)
async def execute_task(request: ExecuteRequest):
    """执行任务"""
    try:
        if request.steps:
            # 执行指定的步骤
            steps = [Step(**s) for s in request.steps]
            results = await mediator.task_engine.execute_steps(steps)
            return ExecuteResponse(
                task_id="batch",
                status="completed",
                result=str(results)
            )
        else:
            # 执行描述性任务
            task = await mediator.task_engine.execute_task(request.task)
            return ExecuteResponse(
                task_id=task.task_id,
                status=task.status.value,
                result=task.result
            )
    except Exception as e:
        logger.error(f"Execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/step")
async def execute_step(step: dict):
    """执行单个步骤"""
    try:
        step_obj = Step(**step)
        result = await mediator.task_engine.executor.execute_step(step_obj)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Step execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class FileRequest(BaseModel):
    """文件操作请求模型"""
    action: str  # read, write, edit, delete, list, mkdir, exists, set_work_folder, get_work_folder
    path: Optional[str] = None
    content: Optional[str] = None
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    folder: Optional[str] = None


@router.post("/file")
async def file_operation(request: FileRequest):
    """文件操作"""
    try:
        step = Step(
            tool="file",
            params={
                "action": request.action,
                "path": request.path,
                "content": request.content,
                "old_content": request.old_content,
                "new_content": request.new_content,
                "folder": request.folder,
            }
        )
        result = await mediator.task_engine.executor.execute_step(step)
        return result
    except Exception as e:
        logger.error(f"File operation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))