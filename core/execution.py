"""Terminal failures are exceptions, never success-shaped model summaries."""
import asyncio


class ExecutionError(RuntimeError):
    outcome = "failed"


class Exhausted(ExecutionError):
    outcome = "exhausted"


class ApprovalDenied(ExecutionError):
    outcome = "denied"


class VerificationError(ExecutionError):
    outcome = "verification_error"


class ExecutionTimedOut(ExecutionError):
    outcome = "timeout"


async def bounded(awaitable, seconds=90):
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise ExecutionTimedOut("Execution timed out; inspect completed side effects before retrying") from exc
