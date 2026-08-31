"""Deployment-time database migration entrypoint for WebChat AI.

Runs the same idempotent schema work that the API performs lazily at startup
(`MongoDB.init_indexes()`) as a standalone, one-shot process. This exists so
orchestrated deployments (CI/CD step, `scripts/deploy.sh migrate`) can:

  1. apply index migrations exactly once per release, before new API/worker
     containers roll out;
  2. fail the deployment fast with a non-zero exit code if MongoDB is
     unreachable or index creation fails;
  3. surface migration status in CI/CD rather than relying on each container
     racing to create the same indexes.

Usage:
    python -m backend.migrations

Exit codes:
    0  migrations applied (or already up to date)
    1  configuration invalid, MongoDB unreachable, or index creation failed

The operation is intentionally idempotent: re-running it after success is a
no-op (MongoDB `create_index` is a no-op for an existing identical index), so
a retried Job can never corrupt an already-migrated schema.
"""

import asyncio
import logging
import sys

from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.logging import attach_sensitive_data_filter, configure_logging

logger = logging.getLogger("webchat_ai")


async def _run_migrations() -> int:
    """Apply schema/index migrations, returning a process exit code."""
    settings = get_settings()

    reachable = await MongoDB.ping()
    if not reachable:
        logger.error(
            "MONGODB_URI unreachable; cannot apply migrations. "
            "Check the database connection before retrying."
        )
        return 1

    logger.info(
        "Applying MongoDB schema migrations against database '%s' (environment=%s).",
        settings.mongodb_db,
        settings.environment,
    )
    await MongoDB.init_indexes()
    logger.info("Schema migrations applied successfully.")
    return 0


async def main() -> int:
    """Run migrations once and return the process exit code."""
    configure_logging()
    attach_sensitive_data_filter()
    try:
        return await _run_migrations()
    except Exception:
        logger.exception("Schema migration failed.")
        return 1
    finally:
        await MongoDB.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
