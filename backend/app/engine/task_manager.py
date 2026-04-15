"""Background task manager for demo lifecycle operations.

Wraps deploy/stop/start/destroy in asyncio background tasks with
per-operation timeouts. HTTP handlers return task_id immediately;
callers poll GET /api/demos/{id}/task/{task_id} for status/progress.
"""
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

# Per-operation timeouts (seconds)
TIMEOUTS = {
    "deploy": 600,   # 10 min — image pulls + init scripts can be slow
    "stop": 60,      # 1 min
    "destroy": 300,  # 5 min — compose down (large clusters take ~90s) + force remove + network cleanup
    "start": 60,     # 1 min
}


class OperationTask:
    def __init__(self, task_id: str, demo_id: str, operation: str):
        self.task_id = task_id
        self.demo_id = demo_id
        self.operation = operation
        self.status = "queued"  # queued | running | done | error | timeout
        self.error = ""
        from ..state.store import DeployProgress
        self.progress = DeployProgress()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "demo_id": self.demo_id,
            "operation": self.operation,
            "status": self.status,
            "error": self.error,
            **self.progress.to_dict(),
        }


# In-memory task registry: task_id → OperationTask
_tasks: dict[str, OperationTask] = {}
# asyncio task handles for cancellation: task_id → asyncio.Task
_asyncio_handles: dict[str, asyncio.Task] = {}


def get_task(task_id: str) -> OperationTask | None:
    return _tasks.get(task_id)


def is_operation_running(demo_id: str) -> bool:
    """Return True if any lifecycle task for this demo is queued or running."""
    for task in _tasks.values():
        if task.demo_id == demo_id and task.status in ("queued", "running"):
            return True
    return False


async def cancel_running_task(demo_id: str) -> None:
    """Cancel any queued/running task for this demo and wait for it to finish."""
    for task in list(_tasks.values()):
        if task.demo_id == demo_id and task.status in ("queued", "running"):
            handle = _asyncio_handles.get(task.task_id)
            if handle and not handle.done():
                handle.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(handle), timeout=5)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            task.status = "cancelled"
            task.error = "Cancelled by destroy"
            task.progress.finished = True
            logger.info(f"Task {task.task_id} ({task.operation} on {demo_id}) cancelled")


async def submit_task(
    demo_id: str,
    operation: str,
    coro,
    progress=None,
) -> OperationTask:
    """Create a background task with timeout. Returns the OperationTask immediately.

    If progress is provided (a DeployProgress instance), it replaces the default
    one created by OperationTask so the caller can share the same progress object.
    """
    task_id = str(uuid.uuid4())[:8]
    task = OperationTask(task_id=task_id, demo_id=demo_id, operation=operation)
    if progress is not None:
        task.progress = progress
    _tasks[task_id] = task

    timeout = TIMEOUTS.get(operation, 300)

    async def _run():
        task.status = "running"
        try:
            await asyncio.wait_for(coro, timeout=timeout)
            task.status = "done"
            task.progress.finished = True
        except asyncio.TimeoutError:
            task.status = "timeout"
            task.error = f"Operation timed out after {timeout}s"
            task.progress.add("error", "error", task.error)
            task.progress.finished = True
            logger.warning(
                f"Task {task_id} ({operation} on {demo_id}) timed out after {timeout}s"
            )
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = "Cancelled"
            task.progress.finished = True
            logger.info(f"Task {task_id} ({operation} on {demo_id}) was cancelled")
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.progress.add("error", "error", str(e))
            task.progress.finished = True
            logger.exception(
                f"Task {task_id} ({operation} on {demo_id}) failed: {e}"
            )
        finally:
            _asyncio_handles.pop(task_id, None)

    handle = asyncio.create_task(_run())
    _asyncio_handles[task_id] = handle
    return task
