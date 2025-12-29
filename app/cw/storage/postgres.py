import atexit
import inspect
import threading
from typing import Dict, Tuple

import asyncpg
from asyncpg import Connection
from loguru import logger
from contextvars import ContextVar

from ..config import config

_registered_logger_connections: set[int] = set()
_registered_logger_lock = threading.Lock()
_query_context: ContextVar[dict[str, str] | None] = ContextVar("_cw_query_context", default=None)


def _connection_query_logger(record) -> None:
    """Log executed queries using loguru without assuming record internals."""
    try:
        query = getattr(record, 'query', None)
        args = getattr(record, 'args', None)
        timeout = getattr(record, 'timeout', None)
        elapsed = getattr(record, 'elapsed', None)
        exception = getattr(record, 'exception', None)

        ctx = _query_context.get()

        parts = ["SQL: {}", query]
        if args:
            parts[0] += " | args={}"
            parts.append(args)
        if timeout is not None:
            parts[0] += " | timeout={}"
            parts.append(timeout)
        if elapsed is not None:
            parts[0] += " | elapsed={}"
            parts.append(elapsed)
        if exception:
            parts[0] += " | exception={}"
            parts.append(exception)
        if ctx and ctx.get('call_site'):
            parts[0] += " | caller={}"
            parts.append(ctx['call_site'])

        logger.debug(*parts)
    except Exception as exc:  # pragma: no cover - safeguard against logging errors
        logger.debug("SQL: <unable to log query> ({})", exc)


class AsyncPGClient:
    def __init__(self, conn: Connection):
        self.conn = conn
        self._ensure_query_logger()

    @staticmethod
    def _call_site() -> str:
        """Capture the first non-storage frame to pinpoint the query caller."""
        frame = inspect.currentframe()
        if not frame:
            return "unknown"

        # Move up: current -> _call_site -> wrapper (e.g. execute) -> caller we want
        frame = frame.f_back  # wrapper
        if frame:
            frame = frame.f_back  # caller

        while frame:
            module = frame.f_globals.get('__name__', '')
            if not module.startswith(__name__):
                func = frame.f_code.co_name
                return f"{module}:{func}:{frame.f_lineno}"
            frame = frame.f_back

        return "unknown"

    async def _run_with_query_context(self, coro_factory):
        token = _query_context.set({'call_site': self._call_site()})
        try:
            return await coro_factory()
        finally:
            _query_context.reset(token)

    async def execute(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return await self._run_with_query_context(lambda: self.conn.execute(sql, *params, **kwargs))

    async def executemany(self, query: str, args, **kwargs):
        sql, _ = self._as_sql_and_params(query, ())
        return await self._run_with_query_context(lambda: self.conn.executemany(sql, args, **kwargs))

    async def fetch(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return await self._run_with_query_context(lambda: self.conn.fetch(sql, *params, **kwargs))

    async def fetchrow(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return await self._run_with_query_context(lambda: self.conn.fetchrow(sql, *params, **kwargs))

    async def fetchval(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return await self._run_with_query_context(lambda: self.conn.fetchval(sql, *params, **kwargs))

    async def fetchmany(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return await self._run_with_query_context(lambda: self.conn.fetchmany(sql, *params, **kwargs))

    def cursor(self, query: str, *args, **kwargs):
        sql, params = self._as_sql_and_params(query, args)
        return self.conn.cursor(sql, *params, **kwargs)

    async def iterate(self, query: str, *args, **kwargs):
        cursor = self.cursor(query, *args, **kwargs)
        async for record in cursor:
            yield record

    def __getattr__(self, item):
        return getattr(self.conn, item)

    def _ensure_query_logger(self) -> None:
        if not hasattr(self.conn, 'add_query_logger'):
            return

        conn_id = id(self.conn)
        with _registered_logger_lock:
            if conn_id in _registered_logger_connections:
                return

            try:
                self.conn.add_query_logger(_connection_query_logger)
            except Exception as exc:  # pragma: no cover - log but do not break queries
                logger.debug("Failed to attach query logger: {}", exc)
                return

            _registered_logger_connections.add(conn_id)

    def _as_sql_and_params(self, query: str, params: Tuple) -> Tuple[str, Tuple]:
        sql: str = query if isinstance(query, str) else str(query)
        return sql, tuple(params)


class ManagedAsyncPGClient(AsyncPGClient):
    """
    AsyncPGClient with lifecycle managed by PostgresManager.
    Provides aclose and async context manager support to release the connection
    back to the pool automatically.
    """

    def __init__(self, conn: Connection, manager: 'PostgresManager', label: str):
        super().__init__(conn)
        self._manager = manager
        self._label = label
        self._closed = False

    async def aclose(self):
        if not self._closed:
            await self._manager.release(self.conn, self._label)
            self._closed = True

    async def __aenter__(self) -> 'ManagedAsyncPGClient':
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()


class PgSession:
    """
    Async context session that acquires a connection from a labeled pool and
    returns an AsyncPGClient. On exit, the connection is released to the pool.
    """

    def __init__(self, manager: 'PostgresManager', label: str):
        self._manager = manager
        self._label = label
        self._conn: Connection | None = None

    async def __aenter__(self) -> AsyncPGClient:
        self._conn = await self._manager.acquire(self._label)
        return AsyncPGClient(self._conn)

    async def __aexit__(self, exc_type, exc, tb):
        if self._conn is not None:
            await self._manager.release(self._conn, self._label)


class PostgresManager:
    """
    Simple PostgreSQL client manager using asyncpg pools.

    - Singleton, thread-safe
    - Labeled pools loaded from configuration (POSTGRES_URL_*)
    - Async acquisition/release of connections
    - Context-managed session helper
    - Cleanup on process exit
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._pools: Dict[str, asyncpg.Pool] = {}
        self._connection_strings: Dict[str, str] = {}
        self._lock = threading.Lock()

        self._load_connection_strings()

        atexit.register(self._cleanup)
        self._initialized = True

    def _get_label_from_env_var(self, env_var: str) -> str:
        if env_var.startswith('POSTGRES_URL_'):
            return env_var[13:].lower()
        elif env_var != 'POSTGRES_URL' and env_var.startswith('POSTGRES_') and env_var.endswith('_URL'):
            return env_var.split('_')[1].lower()
        else:
            return None

    def _load_connection_strings(self):
        # Load labeled URLs: POSTGRES_URL_<LABEL>
        db_parts = {'DB_USER': None, 'DB_PASS': None, 'DB_HOST': None, 'DB_PORT': 5432, 'DB_NAME': None}
        for key, value in config.items():
            if key in db_parts:
                db_parts[key] = value
                continue

            label = self._get_label_from_env_var(key)
            if label is None:
                continue
            if label in self._connection_strings:
                logger.warning(
                    "Postgres connection string for label '{}' already exists, '{}' will override it", 
                    label, key
                )

            self._connection_strings[label] = value
            logger.info("Loaded Postgres URL for label '{}': {}", label, self._hide_password_in_connection_string(value))

        if db_parts['DB_NAME'] is not None:
            default_url = (
                f"postgresql://{db_parts['DB_USER']}:{db_parts['DB_PASS']}@"
                f"{db_parts['DB_HOST']}:{db_parts['DB_PORT']}/{db_parts['DB_NAME']}"
            )
            self._connection_strings['default'] = default_url
            logger.info("Using default Postgres URL: {}", self._hide_password_in_connection_string(default_url))

        if 'default' not in self._connection_strings:
            # Default priority: POSTGRES_URL_DEFAULT > POSTGRES_URL > fallback
            default_url = config.get_postgres_url('default')
            self._connection_strings['default'] = default_url
            logger.info("Using default Postgres URL: {}", self._hide_password_in_connection_string(default_url))

        if self._connection_strings:
            logger.info(
                "Loaded {} Postgres connection strings: {}", 
                len(self._connection_strings), list(self._connection_strings.keys())
            )
        else:
            logger.warning("No Postgres connection strings found")

    def _hide_password_in_connection_string(self, url: str) -> str:
        try:
            if '://' in url and '@' in url:
                proto, rest = url.split('://', 1)
                at = rest.rfind('@')
                if at != -1:
                    auth = rest[:at]
                    host = rest[at + 1:]
                    if ':' in auth:
                        user, pwd = auth.split(':', 1)
                        if user and pwd:
                            return f"{proto}://{user}:***@{host}"
            return url
        except Exception:
            return url

    async def _ensure_pool(self, label: str) -> asyncpg.Pool:
        if label not in self._connection_strings:
            raise ValueError(f"No Postgres connection string found for label '{label}'")

        if label in self._pools:
            return self._pools[label]

        with self._lock:
            if label in self._pools:
                return self._pools[label]
            dsn = self._connection_strings[label]
            logger.info("Open Postgres pool for label '{}'", label)
            # Create pool outside the lock as it's async
        pool = await asyncpg.create_pool(dsn)
        with self._lock:
            self._pools[label] = pool
        return pool

    async def get_pool(self, label: str | None = None) -> asyncpg.Pool:
        if label is None:
            label = 'default'
        return await self._ensure_pool(label)

    async def acquire(self, label: str | None = None) -> Connection:
        pool = await self.get_pool(label)
        return await pool.acquire()

    async def release(self, conn: Connection, label: str | None = None):
        pool = await self.get_pool(label)
        try:
            await pool.release(conn)
        except Exception as e:
            logger.warning("Error releasing Postgres connection: {}", e)

    async def close_pool(self, label: str):
        with self._lock:
            pool = self._pools.get(label)
            if pool is not None:
                del self._pools[label]
            else:
                pool = None
        if pool is not None:
            try:
                await pool.close()
                logger.info("Closed Postgres pool for label '{}'", label)
            except Exception as e:
                logger.error("Error closing Postgres pool for label '{}': {}", label, e)

    async def close_all(self):
        with self._lock:
            labels = list(self._pools.keys())
        for label in labels:
            await self.close_pool(label)

    def session(self, label: str | None = None) -> PgSession:
        return PgSession(self, label or 'default')

    async def get_client(self, label: str | None = None) -> ManagedAsyncPGClient:
        """
        Acquire a connection and wrap it as a ManagedAsyncPGClient.
        Caller must use `async with` or call `.aclose()` to release.
        """
        label = label or 'default'
        conn = await self.acquire(label)
        return ManagedAsyncPGClient(conn, self, label)

    def get_connection_info(self) -> Dict[str, Dict[str, str]]:
        """Return connection info with masked passwords per label."""
        info: Dict[str, Dict[str, str]] = {}
        for label, dsn in self._connection_strings.items():
            info[label] = {
                'dsn': dsn,
                'safe_dsn': self._hide_password_in_connection_string(dsn),
            }
        return info

    def _cleanup(self):
        try:
            labels = list(self._pools.keys()) if hasattr(self, '_pools') else []
            # Schedule async close if possible
            for label in labels:
                try:
                    pool = self._pools.get(label)
                    if pool is None:
                        continue

                    logger.info("Free Postgres pool for label '{}'", label)
                    if hasattr(pool, 'close'):
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(pool.close())
                            logger.info("Free postgres pool for '{}'", label)
                        except RuntimeError:
                            # No running loop; best-effort close synchronously
                            pass
                    del self._pools[label]
                except Exception as e:
                    logger.error("Error during Postgres cleanup for '{}': {}", label, e)
        except Exception as e:
            logger.error("Error during Postgres cleanup: {}", e)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_all()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Best-effort: trigger async cleanup without blocking
        self._cleanup()


# Global helpers
_pg_manager: PostgresManager | None = None


def get_postgres_manager() -> PostgresManager:
    global _pg_manager
    if _pg_manager is None:
        _pg_manager = PostgresManager()
    return _pg_manager


async def get_pg_pool(label: str | None = None) -> asyncpg.Pool:
    return await get_postgres_manager().get_pool(label)


def pg_session(label: str | None = None) -> PgSession:
    return get_postgres_manager().session(label)


async def get_pg_client(label: str | None = None) -> ManagedAsyncPGClient:
    """Convenience function to acquire a managed client for a label."""
    return await get_postgres_manager().get_client(label)
