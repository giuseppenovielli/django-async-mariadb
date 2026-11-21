import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from django_async_mariadb.db.backends.mariadb.async_base import (
    AsyncDatabaseWrapper,
)
from django_async_mariadb.db.utils import async_connections


def database_settings(**overrides):
    values = {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        "NAME": "test_database",
        "USER": "test_user",
        "PASSWORD": "test_password",
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {"charset": "utf8mb4"},
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
        "TIME_ZONE": None,
        "TEST": {},
    }
    values.update(overrides)
    return values


class BackendImportTests(SimpleTestCase):
    def test_async_wrapper_exposes_mysql_introspection(self):
        wrapper = AsyncDatabaseWrapper(database_settings(), "default")

        self.assertEqual(
            wrapper.introspection.identifier_converter("FieldName"),
            "FieldName",
        )

    def test_async_operations_support_django_52_returning_api(self):
        wrapper = AsyncDatabaseWrapper(database_settings(), "default")

        self.assertTrue(hasattr(wrapper.ops, "returning_columns"))

    def test_async_engine_exposes_both_sync_and_async_wrappers(self):
        from django.db.utils import load_backend

        backend = load_backend("django_async_mariadb.db.backends.mariadb")

        self.assertTrue(hasattr(backend, "DatabaseWrapper"))
        self.assertTrue(hasattr(backend, "AsyncDatabaseWrapper"))

    def test_connection_params_translate_django_options_to_asyncmy(self):
        wrapper = AsyncDatabaseWrapper(database_settings(), "default")

        self.assertEqual(
            wrapper.get_connection_params(),
            {
                "charset": "utf8mb4",
                "autocommit": False,
                "db": "test_database",
                "user": "test_user",
                "password": "test_password",
                "host": "127.0.0.1",
                "port": 3306,
            },
        )

    def test_pool_rejects_persistent_connections(self):
        wrapper = AsyncDatabaseWrapper(
            database_settings(
                CONN_MAX_AGE=60,
                OPTIONS={"pool": {"minsize": 1, "maxsize": 2}},
            ),
            "default",
        )

        async def open_pool():
            await wrapper._ensure_pool()

        with self.assertRaises(ImproperlyConfigured):
            import asyncio

            asyncio.run(open_pool())

    def test_sync_wrapper_does_not_forward_async_pool_option(self):
        from django_async_mariadb.db.backends.mariadb.base import DatabaseWrapper

        wrapper = DatabaseWrapper(
            database_settings(OPTIONS={"pool": {"minsize": 1, "maxsize": 2}}),
            "default",
        )

        self.assertNotIn("pool", wrapper.get_connection_params())

    def test_async_connection_handler_is_separate_from_django_connections(self):
        self.assertIsNot(async_connections, __import__(
            "django.db", fromlist=["connections"]
        ).connections)


class FakeCursor:
    def __init__(self):
        self.rowcount = 1
        self.description = None
        self._rows = []
        self.statements = []

    async def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if sql.startswith("SELECT VERSION()"):
            self._rows = [
                ("10.11.11-MariaDB", "STRICT_TRANS_TABLES", "InnoDB", 0, 0, 1)
            ]

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.autocommit_value = False
        self.cursors = []

    def cursor(self, cursor=None):
        value = FakeCursor()
        self.cursors.append(value)
        return value

    async def autocommit(self, value):
        self.autocommit_value = value

    def get_autocommit(self):
        return self.autocommit_value

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def ping(self, reconnect=False):
        return None

    async def ensure_closed(self):
        return None


class AsyncConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_configures_mariadb_metadata_and_session(self):
        fake_connection = FakeConnection()
        wrapper = AsyncDatabaseWrapper(database_settings(), "default")

        with patch(
            "django_async_mariadb.db.backends.mariadb.async_base.Database.connect",
            new_callable=AsyncMock,
            return_value=fake_connection,
        ) as connect:
            await wrapper.connect()

        self.assertEqual(wrapper.mysql_version, (10, 11, 11))
        self.assertTrue(wrapper.mysql_is_mariadb)
        self.assertEqual(wrapper.sql_mode, {"STRICT_TRANS_TABLES"})
        connect.assert_awaited_once_with(
            charset="utf8mb4",
            autocommit=False,
            db="test_database",
            user="test_user",
            password="test_password",
            host="127.0.0.1",
            port=3306,
        )
        statements = [
            statement
            for cursor in fake_connection.cursors
            for statement, _params in cursor.statements
        ]
        self.assertTrue(any("TRANSACTION ISOLATION LEVEL" in sql for sql in statements))

        await wrapper.close()
