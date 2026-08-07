"""Entrypoint for the ARQ background worker.

Run with `python -m backend.workers` (ADR-002 worker entrypoint).

Equivalent to:  arq backend.workers.app.WorkerSettings
"""

import sys

from arq.cli import cli


def main() -> None:
    """Start the ARQ worker using the project WorkerSettings."""
    sys.exit(cli(["backend.workers.app.WorkerSettings"], prog_name="python -m backend.workers"))


if __name__ == "__main__":
    main()
