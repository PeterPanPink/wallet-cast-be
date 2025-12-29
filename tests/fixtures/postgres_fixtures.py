from collections.abc import AsyncGenerator
from typing import Protocol, runtime_checkable

import asyncpg
import pytest
import pytest_asyncio
from asyncpg import Connection, Pool

from app.shared.config import config
from app.shared.storage.postgres import (
    AsyncPGClient,
    ManagedAsyncPGClient,
    PgSession,
    PostgresManager,
)


async def setup_schema(client: AsyncPGClient) -> None:
    pass


@pytest.fixture(scope="session")
def pg_manager() -> PostgresManager:
    """Get the PostgresManager singleton instance."""
    return PostgresManager()


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Get PostgreSQL DSN for testing."""
    return config.get_postgres_url("default")


@pytest_asyncio.fixture
async def pool(pg_dsn: str) -> AsyncGenerator[Pool]:
    """Create a PostgreSQL connection pool for testing."""
    pool = await asyncpg.create_pool(pg_dsn, min_size=1, max_size=5)
    # Set up schema using the pool
    async with pool.acquire() as conn:
        client = AsyncPGClient(conn)  # type: ignore
        await setup_schema(client)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def pg_client(pg_dsn: str) -> AsyncGenerator[ManagedAsyncPGClient]:
    """Provide a managed PostgreSQL client for testing."""
    # Create a direct connection to avoid event loop issues
    conn = await asyncpg.connect(pg_dsn)
    client = AsyncPGClient(conn)
    try:
        await setup_schema(client)
        # Wrap in ManagedAsyncPGClient for compatibility
        managed_client = ManagedAsyncPGClient(conn, None, "default")  # type: ignore
        yield managed_client
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg_session(pg_dsn: str) -> AsyncGenerator[PgSession]:
    """Provide a PostgreSQL session for testing."""
    # Create a direct connection to avoid event loop issues
    conn = await asyncpg.connect(pg_dsn)
    client = AsyncPGClient(conn)
    try:
        await setup_schema(client)

        # Create a simple session-like object
        class SimpleSession:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return AsyncPGClient(self._conn)

            async def __aexit__(self, exc_type, exc, tb):
                pass

        session = SimpleSession(conn)
        yield session  # type: ignore
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def tx_conn(pool: Pool) -> AsyncGenerator[Connection]:
    """Provide a connection with a transaction that gets rolled back after each test."""
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn  # type: ignore
        finally:
            await tx.rollback()


@runtime_checkable
class PoolLike(Protocol):
    """Protocol for pool-like objects that can acquire connections."""

    def acquire(self) -> "ConnectionContextManager":
        """Acquire a connection and return a context manager."""
        ...


@runtime_checkable
class ConnectionContextManager(Protocol):
    """Protocol for connection context managers."""

    async def __aenter__(self) -> Connection:
        """Enter the context and return a connection."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the context."""
        ...


class TxPoolProxy:
    """Pool-like interface that uses a transaction connection."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def acquire(self) -> ConnectionContextManager:
        """Return a context manager that provides the transaction connection."""
        return _TxConnectionContextManager(self._conn)


class _TxConnectionContextManager:
    """Context manager that provides a transaction connection."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def __aenter__(self) -> Connection:
        return self._conn

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        pass


@pytest.fixture
def use_pool(tx_conn: Connection) -> PoolLike:
    """Provide a pool-like interface that uses the transaction connection."""
    return TxPoolProxy(tx_conn)
