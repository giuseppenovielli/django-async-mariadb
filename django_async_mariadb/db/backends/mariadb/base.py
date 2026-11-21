# flake8: noqa: F401
import warnings

from django.conf import settings

# for compatibility with django.db.backends.mysql
try:
    import MySQLdb  # noqa: F401
except ImportError:  # PyMySQL is a supported pure-Python fallback.
    import pymysql

    pymysql.install_as_MySQLdb()

from django.db.backends.mysql.base import (
    DatabaseWrapper as _DatabaseWrapper,
)
from django.db.backends.mysql.base import *

from django_async_mariadb.db.backends.mariadb.async_base import (
    AsyncCursor,
    AsyncCursorDebugWrapper,
    AsyncDatabaseOperations,
    AsyncDatabaseWrapper,
    AsyncServerBindingCursor,
    AsyncServerSideCursor,
)


class DatabaseWrapper(_DatabaseWrapper):
    def get_connection_params(self):
        params = super().get_connection_params()

        # ``pool`` belongs to the asyncmy connection handler. It must not be
        # forwarded to mysqlclient/PyMySQL when Django runs synchronously.
        params.pop("pool", None)

        if not getattr(
            settings, "ASYNC_BACKEND_DISABLE_POOL_WARNING", False
        ) and self.settings_dict.get("OPTIONS", {}).get("pool"):
            warnings.warn(
                "Using the asynchronous Django backend with a connection pool is "
                "unsafe in synchronous mode. Connection pools require the same "
                "event loop for each request to manage state, but the WSGI "
                "handler creates a new event loop for every request.",
                RuntimeWarning,
            )

        return params
