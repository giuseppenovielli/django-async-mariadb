# Django, ORM, and MariaDB

## Declared compatibility

The package declares:

- Django `>=5.2,<6.0`;
- Python `>=3.10`;
- MariaDB 10.5 or newer, with 10.11 as the primary target;
- `asyncmy >=0.2,<0.3`;
- `mysqlclient` `>=2.2,<3` for the synchronous path, with optional PyMySQL
  `>=1.1,<2` fallback.

Actual compatibility must be verified against the version matrix used by the
project. The `<6.0` constraint excludes Django 6.0; it does not mean that
every Django 5.0 or 5.1 version is supported.

## Managers and queryset evaluation

The synchronous `objects` manager remains available. The async path uses:

- `async_objects` as the full name;
- `aobjects` as the short alias.

Methods that perform I/O must be awaitable and use the native `asyncmy` path.
Methods that only build a query may remain regular Django methods:

```python
books = (
    Book.aobjects
    .filter(active=True)
    .select_related("author")
    .order_by("name")
)

async for book in books:
    ...
```

Do not evaluate async querysets with `list()`, `len()`, `bool()`, or synchronous
iteration. Use `async for` and the `a*` methods documented in the README.

## Connections and concurrency

An async connection belongs to the task that uses it. Do not share the same
connection directly between concurrent tasks created with `asyncio.gather()`
or `asyncio.create_task()`.

For parallel operations, use `async_new_connection()` and limit the number of
tasks to the capacity of the server and pool:

```python
from django_async_mariadb.db import async_new_connection

result = await async_new_connection(load_rows())
```

With an async pool, do not use Django persistent connections
(`CONN_MAX_AGE`). The async path must run under ASGI; do not use WSGI to
evaluate pool concurrency.

## Transactions

Use `async_atomic()` for async transactions, rollbacks, and savepoints.
Post-commit callbacks must be registered through `on_commit()` on the async
connection.

```python
from django_async_mariadb.db.transaction import async_atomic

async with async_atomic():
    await Book.aobjects.acreate(name="Django")
```

Do not use Django's synchronous connection directly inside an async context.
Migrations, the admin, and management commands remain on the synchronous path
supported by the Django backend.

## MariaDB

Avoid MySQL-specific SQL, constraints, or features that are not supported by
MariaDB. Always verify:

- date/time types and time zones;
- JSON and value conversions;
- Decimal and numeric precision;
- autocommit and isolation;
- `select_for_update()`;
- `RETURNING` and generated-key behavior;
- result size and streaming;
- `utf8mb4` charset.

## Non-implicit APIs

The library does not make every Django access asynchronous automatically. In
particular, implicit access to deferred fields may perform I/O; after
`defer()` or `only()`, use `await arefresh_from_db()` with the required fields.
`Model.async_save()` and `Model.async_delete()` are the library's public async
model APIs, matching `django-async-backend`.
