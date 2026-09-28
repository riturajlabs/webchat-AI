"""Entrypoint for the background worker (ADR-002, Phase 18A).

Run with `python -m backend.workers`.

The consumer is selected by ``QUEUE_BACKEND``:

* ``arq`` (production default) - the ARQ worker, exactly as before Phase 18A.
  Equivalent to:  arq backend.workers.app.WorkerSettings
* ``mongo`` - the opt-in Mongo consumer (``backend.workers.mongo``), only when
  ``MONGO_QUEUE_ENABLED=true`` (enforced at ``Settings`` construction).
* anything else - fail loud: a typo / unset case must never silently start the
  wrong consumer or a no-op process.
"""

import sys

from backend.core.config import get_settings


def main() -> None:
    """Start the worker configured by QUEUE_BACKEND."""
    settings = get_settings()
    backend = settings.queue_backend.strip().lower()
    if backend == "arq":
        from arq.cli import cli

        sys.exit(cli(["backend.workers.app.WorkerSettings"], prog_name="python -m backend.workers"))
    if backend == "mongo":
        from backend.workers.mongo import run_worker

        sys.exit(run_worker())
    raise SystemExit(
        f"Unknown QUEUE_BACKEND={settings.queue_backend!r}; expected 'arq' or 'mongo'. "
        "Refusing to start a worker under an ambiguous backend."
    )


if __name__ == "__main__":
    main()
