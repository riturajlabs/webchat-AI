"""Safe function registry for queued jobs (Phase 17A).

A closed, explicit mapping of the production task names to their argument
contracts, their worker coroutines and their per-function timeout. It mirrors
``backend.workers.tasks.TASKS`` without importing it eagerly: payload validation
can run in the API process without pulling in Playwright / embedding providers.

Safety rules:

- No ``eval``, ``exec`` and no dynamic import path. ``resolve`` dispatches on a
  fixed table of explicit ``if`` branches; ``function`` is only ever used as a
  dict key and an equality test.
- An unknown function name raises :class:`UnknownFunctionError` at the producer
  boundary, so it can never reach a consumer, let alone be executed.
- Each function declares the exact positional arguments ARQ receives, so a
  payload round-trips losslessly and the Mongo store holds a JSON-safe dict
  while the ARQ adapter still enqueues the same positional args it does today.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final, Union, cast

from arq.typing import WorkerCoroutine
from arq.worker import Function as ArqFunction

from backend.queue.errors import InvalidPayloadError, UnknownFunctionError

# Production task names keyed to the positional ARQ job signature, read from
# backend/workers/tasks.py + backend/workers/jobs/*:
#   ping(ctx)
#   send_email(ctx, payload)
#   crawl_website(ctx, crawl_job_id)
#   process_document(ctx, document_id, run_id)
#   process_website_documents(ctx, website_id)
JOB_ARGUMENTS: Final[dict[str, tuple[str, ...]]] = {
    "ping": (),
    "send_email": ("payload",),
    "crawl_website": ("crawl_job_id",),
    "process_document": ("document_id", "run_id"),
    "process_website_documents": ("website_id",),
}

#: str-typed argument names that must always resolve to a non-empty string.
_REQUIRED_STRING_ARGS: Final[frozenset[str]] = frozenset(
    {"crawl_job_id", "document_id", "website_id"}
)
#: Fields inside the ``send_email`` payload dict, per
#: ``EmailMessage.to_payload()`` (backend/services/mail/base.py).
_EMAIL_PAYLOAD_FIELDS: Final[tuple[str, ...]] = ("to", "subject", "text", "html")
#: Optional delivery metadata (Phase 17B.1). Absent on payloads enqueued before
#: the delivery identity existed, which the worker handles as untracked sends -
#: so these are validated when present, not required.
_EMAIL_DELIVERY_FIELDS: Final[tuple[str, ...]] = ("delivery_id", "idempotency_key", "tenant_id")

#: Fallback timeout for a function with no ARQ-registered timeout. Mirrors
#: ``WorkerSettings.job_timeout`` in backend/workers/app.py.
DEFAULT_JOB_TIMEOUT_SECONDS: Final[int] = 600


def known_names() -> tuple[str, ...]:
    return tuple(JOB_ARGUMENTS)


def validate_function(function: str) -> None:
    """Raise ``UnknownFunctionError`` for a name not in the registry."""
    if function not in JOB_ARGUMENTS:
        raise UnknownFunctionError(
            f"Unknown queue function {function!r}; known functions: {', '.join(known_names())}."
        )


def arguments_for(function: str) -> tuple[str, ...]:
    validate_function(function)
    return JOB_ARGUMENTS[function]


def payload_from_args(function: str, args: tuple[Any, ...] | list[Any]) -> dict[str, Any]:
    """Map ARQ-style positional args to a JSON-safe queue payload."""
    validate_function(function)
    names = JOB_ARGUMENTS[function]
    if len(args) != len(names):
        raise InvalidPayloadError(
            f"Function {function!r} expects {len(names)} positional arg(s) "
            f"{names}; got {len(args)}."
        )
    if function == "send_email":
        payload = args[0]
        if not isinstance(payload, dict):
            raise InvalidPayloadError(
                f"send_email payload must be a dict (received {type(payload).__name__})."
            )
        return dict(payload)
    result: dict[str, Any] = {}
    for name, value in zip(names, args, strict=True):
        result[name] = value
    return result


def args_from_payload(function: str, payload: dict[str, Any]) -> tuple[Any, ...]:
    """Map a queue payload back to ARQ-style positional args."""
    validate_function(function)
    validate_payload(function, payload)
    if function == "send_email":
        return (dict(payload),)
    return tuple(payload.get(name) for name in JOB_ARGUMENTS[function])


def validate_payload(function: str, payload: dict[str, Any]) -> None:
    """Check the payload shape for one registered job.

    Catches producer bugs (and callers reaching past the enqueue helpers) at the
    boundary with clear messages; the adapters store the payload as given.
    """
    validate_function(function)
    if not isinstance(payload, dict):
        raise InvalidPayloadError(
            f"Queue payload must be a dict for {function!r} (received {type(payload).__name__})."
        )
    if function == "ping":
        if payload:
            raise InvalidPayloadError("ping accepts an empty payload.")
        return
    if function == "send_email":
        missing = set(_EMAIL_PAYLOAD_FIELDS) - set(payload)
        if missing:
            raise InvalidPayloadError(
                f"send_email payload is missing required fields: {sorted(missing)}."
            )
        for field in _EMAIL_PAYLOAD_FIELDS:
            if not isinstance(payload.get(field), str):
                raise InvalidPayloadError(f"send_email payload field {field!r} must be a string.")
        for field in _EMAIL_DELIVERY_FIELDS:
            value = payload.get(field)
            if value is not None and not isinstance(value, str):
                raise InvalidPayloadError(
                    f"send_email payload field {field!r} must be a string when present."
                )
        if payload.get("tenant_id") is not None and not isinstance(payload.get("tenant_id"), str):
            raise InvalidPayloadError(
                "send_email payload field 'tenant_id' must be a string when present."
            )
        # A key with no delivery identity is accepted, deliberately. That is the
        # shape a payload enqueued before Phase 17B.1 has, and the worker has an
        # explicit path for it: send it the pre-17B way, keep whatever key it
        # already carried, and log `email_delivery_untracked`. Rejecting it here
        # would silently drop mail that is already in flight - the registry and
        # the worker must agree on which payloads are sendable, and the worker's
        # fallback is the more useful of the two behaviours. The cost is that
        # such a send has no durable row; that is what the warning log is for.
        return
    for name in JOB_ARGUMENTS[function]:
        if name in _REQUIRED_STRING_ARGS:
            value = payload.get(name)
            if not isinstance(value, str) or not value:
                raise InvalidPayloadError(
                    f"Function {function!r} requires a non-empty string arg {name!r} "
                    f"(received {value!r})."
                )
        elif name == "run_id":
            value = payload.get("run_id")
            if value is not None and not isinstance(value, str):
                raise InvalidPayloadError("process_document run_id must be a string or None.")


def resolve(function: str) -> Callable[..., Awaitable[Any]]:
    """Return the registered production coroutine, importing it lazily.

    The imports are explicit and closed; ``function`` is used only to select a
    branch, never interpolated into an import path. The returned callables are
    the SAME objects ARQ dispatches to (including the ``timed_job`` timing
    wrapper and, for ``crawl_website``, the underlying coroutine behind the ARQ
    ``Function``), so the Mongo path keeps the same instrumentation and domain
    behaviour as the ARQ path.
    """
    validate_function(function)
    from backend.workers import tasks

    if function == "ping":
        return tasks.REGISTERED_PING
    if function == "send_email":
        return tasks.REGISTERED_SEND_EMAIL
    if function == "crawl_website":
        return tasks.REGISTERED_CRAWL_WEBSITE
    if function == "process_document":
        return tasks.REGISTERED_PROCESS_DOCUMENT
    if function == "process_website_documents":
        return tasks.REGISTERED_PROCESS_WEBSITE_DOCUMENTS
    raise UnknownFunctionError(f"Unknown queue function {function!r}.")  # pragma: no cover


#: What ``WorkerSettings.functions`` may contain.
ArqRegistryEntry = Union[str, ArqFunction, "WorkerCoroutine"]


def arq_job_timeouts(
    functions: Sequence[object],
    default_timeout: int = DEFAULT_JOB_TIMEOUT_SECONDS,
) -> dict[str, int]:
    """Derive ``{function_name: timeout_seconds}`` from an ARQ registry.

    Reads the real ``arq.worker.Function`` objects rather than hard-coding, so
    the Mongo queue can never drift from the production timeout table: an ARQ
    ``Function``'s own ``timeout_s`` wins, and anything else inherits the
    worker-level default (``WorkerSettings.job_timeout = 600``). This is what
    preserves the production distinction of ``crawl_website`` -> 3600 s versus
    every other task -> 600 s (backend/workers/tasks.py FIND-08).
    """
    from arq.worker import func as arq_func

    resolved: dict[str, int] = {}
    for entry in functions:
        declared = arq_func(cast("ArqRegistryEntry", entry))
        timeout = declared.timeout_s if declared.timeout_s is not None else default_timeout
        resolved[declared.name] = int(timeout)
    return resolved


def job_timeout_seconds(function: str) -> int:
    """Timeout in seconds the Mongo worker must apply to ``function``.

    Sourced from the production ARQ registry (``WorkerSettings.functions`` +
    ``WorkerSettings.job_timeout``) so the two backends cannot disagree.
    """
    validate_function(function)
    from backend.workers.app import WorkerSettings

    timeouts = arq_job_timeouts(WorkerSettings.functions, int(WorkerSettings.job_timeout))
    return timeouts.get(function, DEFAULT_JOB_TIMEOUT_SECONDS)


__all__ = [
    "DEFAULT_JOB_TIMEOUT_SECONDS",
    "ArqRegistryEntry",
    "JOB_ARGUMENTS",
    "arq_job_timeouts",
    "args_from_payload",
    "arguments_for",
    "job_timeout_seconds",
    "known_names",
    "payload_from_args",
    "resolve",
    "validate_function",
    "validate_payload",
]
