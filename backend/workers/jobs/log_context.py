"""ARQ job logging context adapter (FIND-03, OBS-01/OBS-02).

Maps the ARQ job context onto the shared ``request_id``/``tenant_id``
``ContextVar``s so worker log records correlate to the job (and, once the
tenant is known, the tenant) that emitted them. ARQ executes each job in its
own task, and ``create_task`` copies the current context, so values cannot leak
across jobs; the tokens still restore the caller's context on the way out
(mirrors ``crawl_website``'s finally-reset pattern).
"""

from typing import Any

from backend.core.logging import request_id_var, tenant_id_var


def job_request_id(ctx: dict[str, Any]) -> str:
    """Correlate worker records to the ARQ job that produced them."""
    return f"job:{ctx.get('job_id', 'unknown')}"


def request_context(ctx: dict[str, Any]) -> tuple[Any, Any]:
    """Bind request/tenant context for one job; returns tokens for reset.

    The tenant token is captured as a no-op so ``reset_context`` restores the
    caller's tenant (usually "-") even when the job body sets a real tenant
    once it is loaded. Mirrors ``backend.workers.jobs.crawl._run_crawl_job``.
    """
    request_token = request_id_var.set(job_request_id(ctx))
    tenant_token = tenant_id_var.set(tenant_id_var.get())
    return request_token, tenant_token


def reset_context(request_token: Any, tenant_token: Any) -> None:
    """Restore the context captured by ``request_context``."""
    request_id_var.reset(request_token)
    tenant_id_var.reset(tenant_token)
