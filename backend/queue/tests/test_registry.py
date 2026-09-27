"""Registry safety tests: the closed function table is the injection boundary.

An unknown function name must be rejected at the producer boundary and must
never become an import, an attribute lookup on a module, or a call. The last
test pins the registry to the objects ARQ actually dispatches, so the Mongo
backend cannot quietly run a different coroutine (or lose the `timed_job`
instrumentation).
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.queue.errors import InvalidPayloadError, UnknownFunctionError
from backend.queue.registry import (
    DEFAULT_JOB_TIMEOUT_SECONDS,
    JOB_ARGUMENTS,
    args_from_payload,
    arguments_for,
    arq_job_timeouts,
    job_timeout_seconds,
    known_names,
    payload_from_args,
    resolve,
    validate_function,
    validate_payload,
)


def test_known_names_match_the_production_task_registry() -> None:
    from arq.worker import func as arq_func
    from backend.workers.tasks import TASKS

    entries: list[Any] = list(TASKS)
    arq_names = {arq_func(entry).name for entry in entries}
    assert set(known_names()) == arq_names


def test_every_known_function_resolves_to_a_callable() -> None:
    for name in known_names():
        assert callable(resolve(name))


def test_resolve_returns_the_same_object_arq_dispatches() -> None:
    """Same callable => same instrumentation and same domain behaviour."""
    from backend.workers import tasks

    assert resolve("send_email") is tasks.REGISTERED_SEND_EMAIL
    assert resolve("crawl_website") is tasks.REGISTERED_CRAWL_WEBSITE
    assert resolve("process_document") is tasks.REGISTERED_PROCESS_DOCUMENT
    assert resolve("process_website_documents") is tasks.REGISTERED_PROCESS_WEBSITE_DOCUMENTS
    assert resolve("ping") is tasks.REGISTERED_PING


def test_resolve_keeps_the_timed_job_instrumentation() -> None:
    """A non-instrumented coroutine would silently drop Phase 12.1 timing."""
    from backend.workers import tasks

    for name in (
        "send_email",
        "crawl_website",
        "process_document",
        "process_website_documents",
    ):
        assert resolve(name) is getattr(tasks, f"REGISTERED_{name.upper()}")
        # `timed_job` wraps the coroutine, so the resolved object is not the raw
        # job function; the wrapper's closure still holds the original.
        assert getattr(resolve(name), "__wrapped__", None) is not None


@pytest.mark.parametrize(
    "hostile",
    [
        "os.system",
        "__import__",
        "backend.workers.tasks.send_email",
        "send_email.__globals__",
        "",
        "SEND_EMAIL",
        "ping;drop",
    ],
)
def test_unknown_function_is_rejected(hostile: str) -> None:
    with pytest.raises(UnknownFunctionError):
        validate_function(hostile)
    with pytest.raises(UnknownFunctionError):
        resolve(hostile)
    with pytest.raises(UnknownFunctionError):
        arguments_for(hostile)


def test_registry_contains_no_dynamic_import_concatenation() -> None:
    """The mapping is a literal table; no name is ever formatted into a path."""
    from backend.queue import registry

    source = registry.__file__
    assert source is not None
    import inspect

    text = inspect.getsource(registry)
    for banned in ("importlib", "__import__", "eval(", "exec(", "getattr(tasks,"):
        assert banned not in text


def test_job_arguments_match_production_signatures() -> None:
    import inspect

    expected = {
        "ping": (),
        "send_email": ("payload",),
        "crawl_website": ("crawl_job_id",),
        "process_document": ("document_id", "run_id"),
        "process_website_documents": ("website_id",),
    }
    assert JOB_ARGUMENTS == expected
    for name, args in expected.items():
        signature = inspect.signature(resolve(name))
        parameters = [p for p in signature.parameters if p != "ctx"]
        assert tuple(parameters) == args, f"{name} signature drifted"


# ----------------------------------------------------------------------
# payload validation
# ----------------------------------------------------------------------


def test_ping_requires_an_empty_payload() -> None:
    validate_payload("ping", {})
    with pytest.raises(InvalidPayloadError):
        validate_payload("ping", {"unexpected": 1})


def test_send_email_requires_the_documented_payload_fields() -> None:
    """EmailMessage.to_payload() is to/subject/text/html and nothing else."""
    with pytest.raises(InvalidPayloadError):
        validate_payload("send_email", {"to": "a@b.c", "subject": "s", "text": "t"})
    validate_payload("send_email", {"to": "a@b.c", "subject": "s", "text": "t", "html": "<p>h</p>"})


@pytest.mark.parametrize("field", ["to", "subject", "text", "html"])
def test_send_email_fields_must_be_strings(field: str) -> None:
    payload: dict[str, object] = {"to": "a@b.c", "subject": "s", "text": "t", "html": "<p>h</p>"}
    payload[field] = 1
    with pytest.raises(InvalidPayloadError):
        validate_payload("send_email", payload)


def test_send_email_accepts_the_delivery_identity_fields() -> None:
    """The delivery fields are optional strings, and all three may ride along."""
    validate_payload(
        "send_email",
        {
            "to": "a@b.c",
            "subject": "s",
            "text": "t",
            "html": "<p>h</p>",
            "delivery_id": "d1",
            "idempotency_key": "email:t1:d1",
            "tenant_id": "t1",
        },
    )


def test_send_email_rejects_non_string_delivery_fields() -> None:
    for field in ("delivery_id", "idempotency_key", "tenant_id"):
        payload: dict[str, object] = {
            "to": "a@b.c",
            "subject": "s",
            "text": "t",
            "html": "<p>h</p>",
            field: 7,
        }
        with pytest.raises(InvalidPayloadError):
            validate_payload("send_email", payload)


def test_send_email_accepts_a_legacy_key_with_no_delivery_id() -> None:
    """A payload enqueued before Phase 17B.1 must still be sendable.

    The worker has an explicit fallback for this shape: send it the pre-17B way,
    keep the key it already carried, and log `email_delivery_untracked`. If the
    registry rejected it instead, that mail - already queued by the previous
    release - would be dropped silently. The registry and the worker must agree
    on which payloads are sendable, and dropping in-flight mail is the worse
    failure of the two.
    """
    validate_payload(
        "send_email",
        {
            "to": "a@b.c",
            "subject": "s",
            "text": "t",
            "html": "<p>h</p>",
            "idempotency_key": "email:t1:" + "0" * 64,
        },
    )


def test_required_string_args_reject_empty_and_wrong_types() -> None:
    with pytest.raises(InvalidPayloadError):
        validate_payload("crawl_website", {"crawl_job_id": ""})
    with pytest.raises(InvalidPayloadError):
        validate_payload("crawl_website", {"crawl_job_id": 7})
    with pytest.raises(InvalidPayloadError):
        validate_payload("crawl_website", {})
    validate_payload("process_website_documents", {"website_id": "w1"})


def test_process_document_run_id_may_be_null() -> None:
    """Deferred re-processing enqueues a null run_id; that is legitimate."""
    validate_payload("process_document", {"document_id": "d1", "run_id": None})
    validate_payload("process_document", {"document_id": "d1", "run_id": "r1"})
    with pytest.raises(InvalidPayloadError):
        validate_payload("process_document", {"document_id": "d1", "run_id": 5})


# ----------------------------------------------------------------------
# payload <-> args round trip
# ----------------------------------------------------------------------


def test_crawl_payload_round_trips_to_positional_args() -> None:
    payload = {"crawl_job_id": "cj-1"}
    assert args_from_payload("crawl_website", payload) == ("cj-1",)
    assert payload_from_args("crawl_website", ("cj-1",)) == payload


def test_document_payload_round_trips_preserving_null() -> None:
    payload = {"document_id": "d1", "run_id": None}
    assert args_from_payload("process_document", payload) == ("d1", None)
    assert payload_from_args("process_document", ("d1", None)) == payload


def test_email_payload_round_trips_as_a_dict() -> None:
    payload = {"to": "a@b.c", "subject": "s", "text": "t", "html": "<p>h</p>"}
    (args,) = args_from_payload("send_email", payload)
    assert args == payload
    assert payload_from_args("send_email", (args,)) == payload


def test_email_payload_must_be_a_dict() -> None:
    with pytest.raises(InvalidPayloadError):
        payload_from_args("send_email", ("a@b.c",))


def test_wrong_arity_is_rejected() -> None:
    with pytest.raises(InvalidPayloadError):
        payload_from_args("crawl_website", ("a", "b"))
    with pytest.raises(InvalidPayloadError):
        payload_from_args("process_document", ("d1",))


def test_args_from_payload_does_not_alias_the_stored_payload() -> None:
    """A consumer mutating its args must not corrupt the stored document."""
    payload = {"document_id": "d1", "run_id": "r1"}
    args = args_from_payload("process_document", payload)
    assert args == ("d1", "r1")
    assert payload == {"document_id": "d1", "run_id": "r1"}


# ----------------------------------------------------------------------
# timeouts
# ----------------------------------------------------------------------


def test_crawl_keeps_its_own_longer_timeout() -> None:
    """FIND-08: crawl is 3600 s, everything else 600 s. Do not unify them."""
    from backend.core.config import get_settings

    assert job_timeout_seconds("crawl_website") == get_settings().crawl_job_timeout_seconds
    assert job_timeout_seconds("crawl_website") != DEFAULT_JOB_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "name",
    ["ping", "send_email", "process_document", "process_website_documents"],
)
def test_other_jobs_keep_the_global_worker_timeout(name: str) -> None:
    from backend.workers.app import WorkerSettings

    assert job_timeout_seconds(name) == int(WorkerSettings.job_timeout)
    assert job_timeout_seconds(name) == DEFAULT_JOB_TIMEOUT_SECONDS


def test_timeout_table_is_derived_from_the_production_registry() -> None:
    from backend.workers.app import WorkerSettings

    timeouts = arq_job_timeouts(WorkerSettings.functions, int(WorkerSettings.job_timeout))
    assert set(timeouts) == set(known_names())
    assert all(value > 0 for value in timeouts.values())


def test_crawl_context_max_tries_fallback_is_preserved() -> None:
    """`crawl_website` reads ctx.get("max_tries", 3); Mongo supplies 3.

    Supplying 1 (Mongo's literal `max_tries` setting) would change observed
    behaviour, so the value the context carries is pinned to ARQ's 3.
    """
    import inspect

    from backend.workers.jobs import crawl

    # The read lives in the crawl job's inner runner, not in the `crawl_website`
    # entrypoint itself, so scan the module.
    assert 'ctx.get("max_tries", 3)' in inspect.getsource(crawl)
