"""Worker job timing instrumentation (Phase 12.1, opt-in).

ARQ injects `job_id`, `job_try`, `enqueue_time` and `score` into the job
`ctx`; `timed_job` uses those to log the queue wait and the job's execution
duration as a single structured record when `PERF_TIMING_LOG_ENABLED=true`.
The wrapper preserves the underlying coroutine's name (functools.wraps), which
ARQ needs for its `Function` dataclass and result serialization.
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import wraps
from typing import Any, cast

from backend.core.config import get_settings

logger = logging.getLogger("webchat_ai")


@asynccontextmanager
async def chat_stage(stage: str, **context: Any) -> AsyncIterator[None]:
    """Log one `chat_stage` timing record per pipeline step (Phase 12.1, opt-in).

    Emits a structured record (`stage`, `duration_ms`, request_id) when
    `PERF_TIMING_LOG_ENABLED=true`; otherwise it is a no-op so default log
    volume is unchanged. Only non-sensitive identifiers (website/session ids)
    may be passed in `context` - never question text, model output, tokens,
    JWTs or secrets (00-AI-Development-Rules.md §17/§20).
    """
    if not get_settings().perf_timing_log_enabled:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        extra: dict[str, Any] = {"stage": stage, "duration_ms": round(duration_ms, 2)}
        extra.update(context)
        logger.info("chat_stage", extra=extra)


def timed_job[F: Callable[..., Awaitable[Any]]](func: F) -> F:
    """Log queue wait and execution duration for an ARQ job function."""

    @wraps(func)
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        job_id = str(ctx.get("job_id", "unknown"))
        enqueue_time = ctx.get("enqueue_time")
        started = time.perf_counter()
        ok = True
        error: str | None = None
        try:
            return await func(ctx, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised after logging
            ok = False
            error = str(exc)
            raise
        finally:
            if get_settings().perf_timing_log_enabled:
                extra: dict[str, Any] = {
                    "job_type": func.__name__,
                    "job_id": job_id,
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "ok": ok,
                }
                if isinstance(enqueue_time, datetime):
                    queue_wait_ms = (datetime.now(UTC) - enqueue_time).total_seconds() * 1000.0
                    extra["queue_wait_ms"] = round(max(0.0, queue_wait_ms), 2)
                if error is not None:
                    extra["error"] = error
                logger.info("worker_job", extra=extra)

    return cast(F, wrapper)


__all__ = ["chat_stage", "timed_job"]
