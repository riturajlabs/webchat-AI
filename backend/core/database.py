"""MongoDB connection management via the async Motor driver."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.core.config import get_settings


class MongoDB:
    """Lazy singleton around the async Mongo client.

    The client connects on first use, so importing this module has no side
    effects (safe for tests). Close it explicitly on application shutdown.
    """

    _client: AsyncIOMotorClient[Any] | None = None

    @classmethod
    def client(cls) -> AsyncIOMotorClient[Any]:
        if cls._client is None:
            settings = get_settings()
            cls._client = AsyncIOMotorClient[Any](
                settings.mongodb_uri,
                minPoolSize=settings.mongodb_min_pool_size,
                maxPoolSize=settings.mongodb_max_pool_size,
            )
        return cls._client

    @classmethod
    def db(cls) -> AsyncIOMotorDatabase[Any]:
        return cls.client()[get_settings().mongodb_db]

    @classmethod
    async def ping(cls) -> bool:
        """Return True if MongoDB is reachable, False otherwise."""
        try:
            await cls.client().admin.command("ping")
            return True
        except Exception:
            return False

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None
