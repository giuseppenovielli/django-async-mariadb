import os


def mariadb_config():
    return {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        "NAME": os.environ.get("MARIADB_TEST_NAME", "test"),
        "USER": os.environ.get("MARIADB_TEST_USER", ""),
        "PASSWORD": os.environ.get("MARIADB_TEST_PASSWORD", ""),
        "HOST": os.environ.get("MARIADB_TEST_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MARIADB_TEST_PORT", "3306"),
        "CONN_MAX_AGE": 0,
    }


DATABASES = {
    "default": mariadb_config(),
    "other": mariadb_config(),
    "legacy": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django_async_mariadb",
    "test_app",
]

USE_TZ = False
