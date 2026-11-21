# Design decisions

This page explains choices that can surprise you, and why the backend makes
them.

## `AUTOCOMMIT=False` is not supported

**Decision:** The async backend raises `ImproperlyConfigured` when async code
uses a database alias that has `AUTOCOMMIT=False` in `DATABASES`. The error
comes at the first query on that alias. Sync Django is not affected: sync code
can still use an alias with `AUTOCOMMIT=False`.

**What the setting does:** With `AUTOCOMMIT=False`, Django does not commit
anything for you. The database driver starts a transaction before the first
statement, and only `commit()` on the **same** connection saves the work.
`async_atomic()` does not commit either: the transaction stays open after the
block.

**Why:**

- Work that you do not commit by hand is lost without an error. The backend
  closes async connections at the end of each request, and closing a
  connection rolls back its open transaction.
- The backend is moving to one connection for each statement outside
  `async_atomic()`, from the pool or new when there is no pool. Then
  statements of one request can run on different connections, and a manual
  `commit()` cannot save them all.
- Other async ORMs that use one connection for each statement (Tortoise,
  Piccolo, SQLx, SeaORM) also commit each statement outside an explicit
  transaction.

**What to do instead:** Keep `AUTOCOMMIT=True` (the default). Use
[`async_atomic()`](transactions.md) when several statements must commit
together.

## `CONN_MAX_AGE` has no effect

**Decision:** The async backend ignores `CONN_MAX_AGE` and shows a
`RuntimeWarning` when async code connects with an alias that sets it to a
value other than `0`. With a connection pool, a value other than `0` raises
`ImproperlyConfigured`, as in Django.

**Why:** The backend closes async connections at the end of each request, so
no connection lives long enough for a maximum age to matter. For the same
reason, `CONN_HEALTH_CHECKS` only works with a pool: the pool checks a
connection before it gives it out.

**What to do instead:** Remove `CONN_MAX_AGE` from `DATABASES`, or set it to
`0`. To reuse connections between requests, use a
[connection pool](connections.md).
