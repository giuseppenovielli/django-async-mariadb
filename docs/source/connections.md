# Connections

## Connection handler

The connection handler manages database connections for your async backend.

```python
from django_async_mariadb.db import async_connections

connection = async_connections["default"]

async with await connection.cursor() as cursor:
    await cursor.execute("SELECT ...")
    rows = await cursor.fetchall()

await connection.close()
```

- Connections are reused and managed automatically.
- Use `await connection.close()` to manually close a connection if needed.

Each database alias in `DATABASES` gets its own connection within an async
context. See [Concurrency model](concurrency.md) for what that means for
concurrent queries.

## Cursors

`await connection.cursor()` returns an `AsyncCursorWrapper` around the
underlying {pypi}`asyncmy` cursor. The most commonly used methods are:

- `execute` / `executemany` — awaitable;
- `fetchone` / `fetchmany` / `fetchall` — awaitable;
- `close` — awaitable, though the async context manager closes for you.

```python
async with await connection.cursor() as cursor:
    await cursor.execute("SELECT 1")
    row = await cursor.fetchone()
```

The wrapper is a thin proxy: it implements `execute` and `executemany` itself
(to run Django's `execute_wrappers` and translate database errors), and passes
everything else straight through to the asyncmy cursor. So the rest of
asyncmy's [cursor
API](https://www.asyncmy.org/asyncmy3/docs/api/cursors.html) is available too.
Because those come from asyncmy unchanged, they keep asyncmy's own calling
convention rather than being uniformly awaitable:

- `scroll` and `close` — `await` them;
- `stream` — an async generator: `async for row in cursor.stream(...)`;
- `copy` — an async context manager: `async with cursor.copy(...)`;
- `nextset` — a plain synchronous call;
- `rowcount`, `rownumber` and `description` — attributes, not calls.

```python
async with await connection.cursor() as cursor:
    await cursor.execute("SELECT id, name FROM app_book")

    print(cursor.rowcount)
    print([column.name for column in cursor.description])
```

Cursors are also async-iterable, which streams rows without materializing them
all at once:

```python
async with await connection.cursor() as cursor:
    await cursor.execute("SELECT id FROM app_book")

    async for row in cursor:
        print(row)
```

## Connection pooling

Pooling is included in the package and is enabled with the database `OPTIONS`:

```python
"OPTIONS": {"pool": {"minsize": 1, "maxsize": 10}}
```

```{warning}
Connection pooling is not supported when running under a WSGI server
(including the Django development server), because WSGI creates a new event
loop for each request. This prevents reliable management of connection pool
state.

To disable the warning, set `ASYNC_BACKEND_DISABLE_POOL_WARNING=True`.
```

Under ASGI, connections are returned to the pool at the end of each request by
the [request signals](setup.md#request-signals) the app connects on startup.
