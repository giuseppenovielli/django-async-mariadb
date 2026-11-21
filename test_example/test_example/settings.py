import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-default-key")
DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django_async_mariadb",
    "books",
]


ROOT_URLCONF = "test_example.urls"

DATABASES = {
    "default": {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        "NAME": os.environ.get("MARIADB_TEST_NAME", "test"),
        "USER": os.environ.get("MARIADB_TEST_USER", ""),
        "PASSWORD": os.environ.get("MARIADB_TEST_PASSWORD", ""),
        "HOST": os.environ.get("MARIADB_TEST_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MARIADB_TEST_PORT", "3306"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "pool": {
                "minsize": 2,
                "maxsize": 4,
            }
        },
    }
}

WSGI_APPLICATION = "test_example.wsgi.application"
