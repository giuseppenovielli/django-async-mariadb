# Testing and TDD

## Methodology

Every new function, bug fix, or behavior change must follow:

1. **Red**: add a test that fails for the expected reason.
2. **Green**: implement the minimum required to make the test pass.
3. **Refactor**: improve structure and readability while keeping tests green.

Tests must verify public behavior, not only implementation details.

## Test types

### Unit tests

Use `unittest` and `SimpleTestCase` for logic that does not require a MariaDB
server. They are suitable for verifying:

- async manager exposure;
- query compilation;
- connection option conversion;
- argument validation;
- pool and wrapper behavior without opening the database.

Run:

```bash
cd /percorso/verso/django_async_mariadb
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

### System check

```bash
.venv/bin/python -m django check --settings=tests.settings
```

### MariaDB integration

The runner creates a temporary schema named `codex_async_*`, creates the
required tables, runs the checks, and removes the schema in the `finally` block.
Use it only with a test user authorized to create and remove schemas.

Configure a local `.env` without versioning credentials:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=utente_test
DB_PASSWORD=password_test
```

Run:

```bash
.venv/bin/python -m tests.mariadb_integration_runner
ASYNC_MARIADB_POOL=1 .venv/bin/python -m tests.mariadb_integration_runner
```

The integration test should cover, where applicable:

- connection and closing;
- creation, updates, and refresh;
- dates, time zones, JSON, and Decimal;
- `defer()` and `only()`;
- direct and reverse relationships, `select_related()`, and prefetching;
- `aiterator()` and raw queries;
- M2M with a `through` model and `m2m_changed` signals;
- commit, rollback, savepoints, and `on_commit()`;
- `select_for_update()`;
- pool and concurrency with task-isolated connections.

Do not run the runner against a real application database.

### Benchmark

The benchmark must report hardware, operating system, Python, Django, driver,
MariaDB, dataset, iterations, and load levels. Results are indicative and do
not constitute a general performance guarantee.

```bash
.venv/bin/python -m tests.benchmark_mariadb
```

## Pre-release verification

Before creating a local wheel or a release:

1. run `django check`;
2. run all unit tests;
3. run MariaDB integration with and without the pool;
4. verify the wheel by installing it in a clean virtual environment;
5. check `pip show`, dependencies, and package version;
6. document any tests that could not be run and why.
