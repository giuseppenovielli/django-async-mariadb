# Async Django ORM

```{container} badges
[![CI status](https://img.shields.io/github/actions/workflow/status/giuseppenovielli/django_async_mariadb/test.yml?logo=github&style=for-the-badge&labelColor=%23282828)](https://github.com/giuseppenovielli/django_async_mariadb/actions)
[![Latest Version in PyPI](https://img.shields.io/pypi/v/django-async-mariadb.svg?style=for-the-badge)](https://pypi.org/project/django-async-mariadb/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/django-async-mariadb.svg?style=for-the-badge)](https://pypi.org/project/django-async-mariadb/)
[![Monthly downloads](https://static.pepy.tech/personalized-badge/django-async-mariadb?period=month&units=international_system&left_color=grey&right_color=blue&left_text=downloads/month)](https://pepy.tech/projects/django-async-mariadb)
```

Django's `a`-prefixed ORM methods (`aget`, `acreate`, …) are thin
`sync_to_async` wrappers: the query still runs on a threadpool, on a
synchronous connection. **django-async-mariadb** replaces the database layer
itself, so queries are issued on a real asyncio connection through
{pypi}`asyncmy`, with async transactions, async cursors and optional
connection pooling.

The project is **production ready**: the API is stable, and each release is
pinned to the Django feature release it was generated against, so upgrades stay
predictable.

```{warning}
**Run this under ASGI.** django-async-mariadb is developed for ASGI, and that
is the only mode it is supported in. Under WSGI — including the Django
development server — it behaves inconsistently, because WSGI creates a new
event loop for each request and the async connection state cannot be managed
reliably across them. Connection pooling in particular is not supported there.
```

## Feature Summary

- Database layer
  - [Connection handler](connections.md#connection-handler)
  - [Cursors](connections.md#cursors)
  - [Connection pooling](connections.md#connection-pooling)
  - [Request signals](setup.md#request-signals)
- ORM
  - [`AsyncModelMixin`](orm.md#asyncmodelmixin) — `async_save()` / `async_delete()`
  - [Managers](orm.md#managers) — the `async_objects` manager
  - [Compatibility matrix](orm.md#compatibility)
- Transactions
  - [Basic usage](transactions.md#basic-usage)
  - [Nested transactions (savepoints)](transactions.md#nested-transactions-savepoints)
  - [`on_commit` callbacks](transactions.md#using-on_commit-with-async-transactions)
- Testing
  - [`AsyncioTestCase`](testing.md#asynciotestcase)
  - [`AsyncioTransactionTestCase`](testing.md#asynciotransactiontestcase)
- Implementation details
  - [Concurrency and parallelism](concurrency.md)
  - [Running queries in parallel](concurrency.md#running-queries-in-parallel)

## Installation

```bash
pip install django-async-mariadb
```

The package uses {pypi}`asyncmy` for asynchronous connections and PyMySQL as the
synchronous fallback. Enable pooling with the database `OPTIONS` setting.

The package tracks Django's major and minor version, so the release you install
is pinned to the Django feature release it was generated against.

| django-async-mariadb | Django  |
| -------------------- | ------- |
| `5.2.x`              | `5.2.x` |

Part of the ORM layer is generated from Django's own source *ahead of time*:
the generated modules are committed to git and shipped in the wheel, so nothing
is downloaded or rewritten at install time and nothing is patched at runtime. A
Django feature release therefore gets a matching django-async-mariadb feature
release rather than a loosened version range. See
[Code generation](contribute.md#code-generation).

## Getting started

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        "NAME": "mydb",
        "USER": "app",
        "PASSWORD": "...",
        "HOST": "localhost",
        "PORT": "5432",
    },
}

INSTALLED_APPS = [
    # ...
    "django_async_mariadb",
]
```

::::{tab-set}
:::{tab-item} ORM
```python
from django.db import models
from django_async_mariadb.db import async_connections
from django_async_mariadb.db.models.base import AsyncModelMixin
from django_async_mariadb.db.transaction import async_atomic


class Book(AsyncModelMixin, models.Model):
    name = models.CharField(max_length=100)


async def notify(book_id: int) -> None:
    ...


async def main() -> None:
    connection = async_connections["default"]

    async with async_atomic():
        book = await Book.async_objects.acreate(name="Django")

        # async callbacks are supported; runs only if the transaction commits
        await connection.on_commit(lambda: notify(book.pk))

        book.name = "Django Async"
        await book.async_save(update_fields=["name"])

        async with async_atomic():  # savepoint
            await Book.async_objects.filter(name="draft").adelete()

    print(await Book.async_objects.acount())

    async for row in Book.async_objects.order_by("name"):
        print(row.pk, row.name)
```
:::

:::{tab-item} Cursor
```python
from django_async_mariadb.db import async_connections
from django_async_mariadb.db.transaction import async_atomic


async def notify(book_id: int) -> None:
    ...


async def main() -> None:
    connection = async_connections["default"]

    async with async_atomic():
        async with await connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO app_book (name) VALUES (%s) RETURNING id",
                ["Django"],
            )
            (book_id,) = await cursor.fetchone()

            # async callbacks are supported; runs only if the transaction commits
            await connection.on_commit(lambda: notify(book_id))

            await cursor.executemany(
                "INSERT INTO app_book (name) VALUES (%s)",
                [["a"], ["b"]],
            )

    async with await connection.cursor() as cursor:
        await cursor.execute("SELECT id, name FROM app_book ORDER BY name")

        print(cursor.rowcount)

        async for row in cursor:
            print(row)
```
:::

::::

```{toctree}
:maxdepth: 2
:hidden:

setup
connections
orm
transactions
testing
concurrency
design
contribute
```
