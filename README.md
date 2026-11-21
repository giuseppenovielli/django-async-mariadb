# Async Django ORM for MariaDB

Async Django ORM and MariaDB database backend.

Django's `a`-prefixed ORM methods (`aget`, `acreate`, …) are thin
`sync_to_async` wrappers: the query still runs on a threadpool, on a
synchronous connection. **django-async-mariadb** replaces the database layer
itself, so queries are issued on a real asyncio connection through
[asyncmy](https://github.com/long2ice/asyncmy), with async transactions, async
cursors and optional connection pooling — no thread emulation.

📖 **[Read the documentation](docs/source/index.md)**

---

## Compatibility

The package tracks Django's major and minor version, so the release you install
is pinned to the Django feature release it was generated against.

| Component | `django-async-backend` (original source) | `django-async-mariadb` (this fork) |
| --------- | --------------------------------------- | ---------------------------------- |
| Package version | `6.1.5` | `5.2.0` |
| Python | `>=3.12` | `3.10+` |
| Django | `>=6.1` (`6.1.x`) | `>=5.2,<5.3` (`5.2.x`) |
| Database backend | PostgreSQL | MariaDB `10.11` |
| Async driver | `psycopg` 3 | `asyncmy` |
| Async ORM | Original implementation | Original implementation adapted to Django 5.2 |
| Source baseline | — | `django-async-backend` `6.1.5` |

Part of the ORM layer is generated from Django's own source, so a Django feature
release gets a matching django-async-mariadb feature release rather than a
loosened version range. Patch releases within a line are ordinary bugfix
releases and are safe to upgrade to.

> [!IMPORTANT]
> **Run this under ASGI.** django-async-mariadb is developed for ASGI, and that
> is the only mode it is supported in. Under WSGI — including the Django
> development server — it behaves inconsistently, because WSGI creates a new
> event loop for each request and the async connection state cannot be managed
> reliably across them. Connection pooling in particular is not supported
> there.

## Installation

```bash
pip install "django-async-mariadb[mysqlclient] @ git+https://github.com/giuseppenovielli/django_async_mariadb.git"
```

The package is currently installed from GitHub. It uses `asyncmy` for
asynchronous connections and `mysqlclient` for the synchronous Django
compatibility path. If a native client library cannot be installed, use the
optional pure-Python fallback instead:

```bash
pip install "django-async-mariadb[pymysql] @ git+https://github.com/giuseppenovielli/django_async_mariadb.git"
```

Connection pooling is enabled through the database `OPTIONS` setting.

The package tracks Django's major and minor version — this line targets Django
`5.2.x` — because a large part of the ORM layer is generated from
Django's own source.

## Quick start

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        ...
    },
}

INSTALLED_APPS = [
    ...
    "django_async_mariadb",
]
```

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

Or drop to a raw async cursor:

```python
async with await connection.cursor() as cursor:
    await cursor.execute("SELECT id, name FROM app_book ORDER BY name")

    print(cursor.rowcount)

    async for row in cursor:
        print(row)
```

> [!WARNING]
> **Async does not mean parallel.** A task gets one connection per database
> alias, and every ORM and cursor call in that task takes turns on it — so
> awaiting several queries in a row does not make them run concurrently.
>
> The connection is owned by the task that first used it, so you cannot fan out
> onto it either: using it from another task — `asyncio.create_task()`,
> `asyncio.gather()`, `asyncio.TaskGroup` — raises `RuntimeError`. Wrapping the
> fan-out in a single `async_atomic()` block does **not** make it safe. To run
> queries in parallel, give each task its own connection with
> `async_new_connection` — sparingly, since each call opens a real connection
> and a wide fan-out can exhaust the server's limit.

## Supported methods

Legend: ✅ supported · ❌ not supported · ⚠️ supported with caveats

### QuerySet methods

| methods                             | supported | comments |
| ----------------------------------- | --------- | -------- |
| `Model.objects.aget`                | ✅        |          |
| `Model.objects.acreate`             | ✅        |          |
| `Model.objects.acount`              | ✅        |          |
| `Model.objects.none`                | ✅        |          |
| `Model.objects.abulk_create`        | ✅        |          |
| `Model.objects.abulk_update`        | ✅        |          |
| `Model.objects.aget_or_create`      | ✅        |          |
| `Model.objects.aupdate_or_create`   | ✅        |          |
| `Model.objects.aearliest`           | ✅        |          |
| `Model.objects.alatest`             | ✅        |          |
| `Model.objects.afirst`              | ✅        |          |
| `Model.objects.alast`               | ✅        |          |
| `Model.objects.ain_bulk`            | ✅        |          |
| `Model.objects.adelete`             | ✅        |          |
| `Model.objects.aupdate`             | ✅        |          |
| `Model.objects.aexists`             | ✅        |          |
| `Model.objects.acontains`           | ✅        |          |
| `Model.objects.aexplain`            | ✅        |          |
| `Model.objects.araw`                | ❌        |          |
| `Model.objects.all`                 | ✅        |          |
| `Model.objects.filter`              | ✅        |          |
| `Model.objects.exclude`             | ✅        |          |
| `Model.objects.complex_filter`      | ✅        |          |
| `Model.objects.union`               | ✅        |          |
| `Model.objects.intersection`        | ✅        |          |
| `Model.objects.difference`          | ✅        |          |
| `Model.objects.select_related`      | ✅        |          |
| `Model.objects.select_for_update`   | ✅        |          |
| `Model.objects.prefetch_related`    | ❌        |          |
| `Model.objects.aaggregate`          | ✅        |          |
| `Model.objects.annotate`            | ✅        |          |
| `Model.objects.order_by`            | ✅        |          |
| `Model.objects.distinct`            | ✅        |          |
| `Model.objects.extra`               | ✅        |          |
| `Model.objects.reverse`             | ✅        |          |
| `Model.objects.defer`               | ⚠️        | not safe for async, will not be implemented — use `values`/`values_list` |
| `Model.objects.only`                | ⚠️        | not safe for async, will not be implemented — use `values`/`values_list` |
| `Model.objects.using`               | ✅        |          |
| `Model.objects.resolve_expression`  | ✅        |          |
| `Model.objects.ordered`             | ✅        |          |
| `Model.objects.values`              | ✅        |          |
| `Model.objects.values_list`         | ✅        |          |
| `Model.objects.dates`               | ✅        |          |
| `Model.objects.datetimes`           | ✅        |          |
| `Model.objects.alias`               | ✅        |          |
| `Model.objects.aiterator`           | ❌        |          |

### Dunder methods

| methods            | supported | comments |
| ------------------ | --------- | -------- |
| `__aiter__`        | ✅        |          |
| `__iter__`         | ⚠️        | raises `TypeError` — use `async for obj in qs` |
| `__len__`          | ⚠️        | raises `TypeError` — use `await qs.acount()` |
| `__contains__`     | ⚠️        | falls back to `__iter__`, so it raises `TypeError` too |
| `__bool__`         | ⚠️        | truth-testing falls back to `__len__`, so `if qs:` raises `TypeError` — use `await qs.aexists()` |
| `__repr__`         | ✅        |          |
| `__and__`          | ✅        |          |
| `__or__`           | ✅        |          |
| `__xor__`          | ✅        |          |
| `__getitem__`      | ✅        |          |

### Model methods

Django's own `a*` methods keep their existing behavior; the genuinely async
equivalents are the names in the comments column.

| methods                  | supported | comments                 |
| ------------------------ | --------- | ------------------------ |
| `Model.asave`            | ✅        | `async_save`             |
| `Model.adelete`          | ✅        | `async_delete`           |
| `Model.arefresh_from_db` | ✅        | `async_refresh_from_db`  |

### RawQuerySet

Not supported ❌

### Related managers

Not supported ❌ — `instance.<related>.all()` is the sync ORM. See
[Pitfalls](#pitfalls).

## Disclaimer

This project was generated entirely with the assistance of artificial
intelligence. Review, test, and supervise the code carefully before using it
in production. No guarantee is made that the implementation is suitable for a
specific application or production workload.

## Fork and scope

This project is a fork of the original
[django-async/django-async-backend](https://github.com/django-async/django-async-backend),
adapted to support Django 5.2 LTS and MariaDB. It does not introduce new ORM
features or modify the async ORM functionality implemented by the original
author; the changes are limited to the compatibility and database-backend
adaptations required for these targets.

## Author

Giuseppe Novielli — [novielligiuseppe@gmail.com](mailto:novielligiuseppe@gmail.com)

## License

This project is released under the [Apache License 2.0](LICENSE).
