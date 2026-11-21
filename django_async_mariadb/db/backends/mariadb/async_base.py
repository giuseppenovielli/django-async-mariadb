"""Async MariaDB connection wrapper backed by :mod:`asyncmy`.

The ORM layer in this package is deliberately kept separate from Django's
synchronous MySQL backend. Django still supplies the SQL compiler, feature
flags, schema editor, introspection, and migration support; this module only
replaces the connection and cursor boundary for async callers.
"""

import re

from django.core.exceptions import ImproperlyConfigured

try:
    import MySQLdb  # noqa: F401
except ImportError:  # PyMySQL is an optional pure-Python fallback.
    try:
        import pymysql
    except ImportError as exc:
        raise ImproperlyConfigured(
            "Install django-async-mariadb[mysqlclient] or "
            "django-async-mariadb[pymysql] for the synchronous Django "
            "compatibility path."
        ) from exc

    pymysql.install_as_MySQLdb()

from django.db.backends.base.base import NO_DB_ALIAS
from django.db.backends.mysql.base import DatabaseWrapper

from django_async_mariadb.db.backends.base.base import BaseAsyncDatabaseWrapper
from django_async_mariadb.db.backends.utils import (
    AsyncCursorDebugWrapper as BaseAsyncCursorDebugWrapper,
)

try:
    import asyncmy as Database
except ImportError as exc:  # pragma: no cover - exercised at installation time
    raise ImproperlyConfigured(
        "Error loading asyncmy. Install django-async-mariadb with asyncmy."
    ) from exc


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")
_ISOLATION_LEVELS = {
    "read uncommitted",
    "read committed",
    "repeatable read",
    "serializable",
}


class AsyncDatabaseOperations(DatabaseWrapper.ops_class):
    compiler_module = "django_async_mariadb.db.models.sql.compiler"

    def returning_columns(self, fields):
        """Bridge Django 6 compiler naming to Django 5.2 operations."""
        parent_method = getattr(super(), "returning_columns", None)
        if parent_method is not None:
            return parent_method(fields)
        return self.return_insert_columns(fields)

    async def last_executed_query(self, cursor, sql, params):
        """Return a useful debug string without relying on driver internals."""
        query = getattr(cursor, "_last_executed", None)
        if query:
            return query.decode() if isinstance(query, bytes) else query
        return sql


class AsyncDatabaseWrapper(BaseAsyncDatabaseWrapper):
    """Django database wrapper using one task-owned asyncmy connection."""

    vendor = DatabaseWrapper.vendor
    display_name = "MariaDB"
    data_types = DatabaseWrapper.data_types
    data_type_check_constraints = DatabaseWrapper.data_type_check_constraints
    data_types_suffix = DatabaseWrapper.data_types_suffix
    operators = DatabaseWrapper.operators
    pattern_esc = DatabaseWrapper.pattern_esc
    pattern_ops = DatabaseWrapper.pattern_ops

    Database = Database
    features_class = DatabaseWrapper.features_class
    ops_class = AsyncDatabaseOperations
    introspection_class = DatabaseWrapper.introspection_class

    def __init__(self, settings_dict, alias=None):
        super().__init__(settings_dict, alias)
        self._pool = None
        self._pooled_connection = False
        self._mysql_server_data = None
        self._mysql_version = None
        self._mysql_is_mariadb = True
        self._sql_mode = set()
        self.isolation_level = None
        self.introspection = self.introspection_class(self)

    @property
    def mysql_server_data(self):
        return self._mysql_server_data or {
            "version": "MariaDB",
            "sql_mode": "",
            "default_storage_engine": "InnoDB",
            "sql_auto_is_null": False,
            "lower_case_table_names": False,
            "has_zoneinfo_database": False,
        }

    @property
    def mysql_server_info(self):
        return self.mysql_server_data["version"]

    @property
    def mysql_version(self):
        return self._mysql_version or (10, 5)

    @property
    def mysql_is_mariadb(self):
        return self._mysql_is_mariadb

    @property
    def sql_mode(self):
        return self._sql_mode

    @property
    def pool(self):
        """Return the loop-local asyncmy pool, if one has been opened."""
        return self._pool

    async def get_database_version(self):
        return self.mysql_version

    async def _ensure_pool(self):
        pool_options = self.settings_dict["OPTIONS"].get("pool")
        if not pool_options or self.alias == NO_DB_ALIAS:
            return None
        if self.settings_dict.get("CONN_MAX_AGE", 0) != 0:
            raise ImproperlyConfigured(
                "asyncmy pooling does not support persistent connections."
            )
        if self._pool is None:
            if pool_options is True:
                pool_options = {}
            connect_params = self.get_connection_params()
            connect_params["autocommit"] = True
            self._pool = await Database.create_pool(
                **connect_params, **pool_options
            )
        return self._pool

    async def close_pool(self):
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    def get_connection_params(self):
        settings_dict = self.settings_dict
        options = dict(settings_dict.get("OPTIONS") or {})

        isolation_level = options.pop("isolation_level", "read committed")
        if isolation_level:
            isolation_level = isolation_level.lower()
            if isolation_level not in _ISOLATION_LEVELS:
                raise ImproperlyConfigured(
                    "Invalid transaction isolation level %r. Use one of %s."
                    % (isolation_level, ", ".join(sorted(_ISOLATION_LEVELS)))
                )
        self.isolation_level = isolation_level

        # These options belong to Django or to the pool, not to asyncmy.
        for key in (
            "pool",
            "use_unicode",
            "server_side_binding",
        ):
            options.pop(key, None)

        params = {
            "charset": options.pop("charset", "utf8mb4"),
            "autocommit": False,
        }
        if settings_dict["NAME"]:
            params["db"] = settings_dict["NAME"]
        if settings_dict["USER"]:
            params["user"] = settings_dict["USER"]
        if settings_dict["PASSWORD"]:
            params["password"] = settings_dict["PASSWORD"]
        if settings_dict["HOST"]:
            if settings_dict["HOST"].startswith("/"):
                params["unix_socket"] = settings_dict["HOST"]
            else:
                params["host"] = settings_dict["HOST"]
        if settings_dict["PORT"]:
            params["port"] = int(settings_dict["PORT"])

        # Pass through documented asyncmy connection options such as ssl,
        # connect_timeout, sql_mode and local_infile.
        params.update(options)
        return params

    async def get_new_connection(self, conn_params):
        pool = await self._ensure_pool()
        if pool is not None:
            self.connection = await pool.acquire()
            self._pooled_connection = True
        else:
            self.connection = await Database.connect(**conn_params)
            self._pooled_connection = False
        return self.connection

    async def _load_server_data(self):
        async with await self.cursor() as cursor:
            await cursor.execute(
                "SELECT VERSION(), @@sql_mode, @@default_storage_engine, "
                "@@sql_auto_is_null, @@lower_case_table_names, "
                "CONVERT_TZ('2001-01-01 01:00:00', 'UTC', 'UTC') IS NOT NULL"
            )
            row = await cursor.fetchone()

        version = str(row[0])
        match = _VERSION_RE.match(version)
        if not match:
            raise ImproperlyConfigured(
                "Unable to determine MariaDB version from %r" % version
            )
        self._mysql_version = tuple(
            int(part) for part in match.groups() if part is not None
        )
        mode = row[1] or ""
        self._sql_mode = set(mode.split(","))
        self._mysql_server_data = {
            "version": version,
            "sql_mode": mode,
            "default_storage_engine": row[2],
            "sql_auto_is_null": bool(row[3]),
            "lower_case_table_names": bool(row[4]),
            "has_zoneinfo_database": bool(row[5]),
        }

    async def init_connection_state(self):
        await self._load_server_data()
        await super().init_connection_state()
        assignments = []
        if self.features.is_sql_auto_is_null_enabled:
            assignments.append("SET SQL_AUTO_IS_NULL = 0")
        if self.isolation_level:
            assignments.append(
                "SET SESSION TRANSACTION ISOLATION LEVEL %s"
                % self.isolation_level.upper()
            )
        if assignments:
            async with await self.cursor() as cursor:
                await cursor.execute("; ".join(assignments))

    def create_cursor(self, name=None):
        if name:
            from asyncmy.cursors import SSCursor

            return self.connection.cursor(cursor=SSCursor)
        return self.connection.cursor()

    async def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            await self.connection.autocommit(autocommit)

    async def is_usable(self):
        if self.connection is None:
            return False
        try:
            await self.connection.ping(reconnect=False)
        except Database.Error:
            return False
        return True

    async def _close(self):
        if self.connection is None:
            return
        with self.wrap_database_errors:
            if self._pooled_connection and self._pool is not None:
                self._pool.release(self.connection)
                self._pooled_connection = False
            else:
                await self.connection.ensure_closed()

    def make_debug_cursor(self, cursor):
        return AsyncCursorDebugWrapper(cursor, self)


class AsyncCursor:
    """Marker kept for API parity with the upstream backend."""


class AsyncCursorDebugWrapper(BaseAsyncCursorDebugWrapper):
    pass


# The public aliases are intentionally simple: asyncmy cursors are already
# awaitable and async-iterable, so the generic wrapper supplies Django's error
# translation and execute-wrapper hooks.
AsyncServerBindingCursor = AsyncCursor
AsyncServerSideCursor = AsyncCursor
