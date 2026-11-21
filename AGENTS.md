# AGENTS.md

## Supported stack

- Python 3.10+.
- Django `>=5.2,<6.0`.
- MariaDB 10.11 as the primary target.
- Async driver `asyncmy` with sync `mysqlclient` and optional PyMySQL fallback.

## Development rules

The operational guides are collected in [docs/coding/](docs/coding/):
[index](docs/coding/index.md), [testing](docs/coding/testing.md), and
[Django/MariaDB](docs/coding/django.md).

1. Prefer small, readable, focused changes.
2. Reuse existing utilities before introducing new abstractions.
3. Avoid dependencies on the host project and hardcoded configuration.
4. Keep the backend, ORM, transactions, connections, and tests separated.
5. Use explicit names and comments only for non-obvious technical constraints.
6. Do not place secrets, credentials, or local data in versioned files.
7. Apply TDD for new logic or behavior changes:
   `Red -> Green -> Refactor`.
8. Async ORM APIs must not introduce `sync_to_async` into the library code.
   Lazy query-building methods may remain synchronous; I/O must be awaitable.
9. Do not hardcode credentials. MariaDB tests must use environment variables
   or an unversioned local `.env` file and temporary schemas.
10. Do not modify code, settings, or documentation in the host repository.
11. Preserve MariaDB 10.11 compatibility and avoid MySQL features not
    supported by MariaDB.
12. Before delivery, run unit tests, `django check`, Python compilation, and,
    when available, the real MariaDB test.
13. Write all Git commit messages in English.

## Django and MariaDB rules

- Runtime code must support Django 5.2 and MariaDB 10.11.
- Models and queries must avoid constructs unsupported by MariaDB.
- APIs that perform I/O must have a native async path.
- Lazy query-building methods may be regular Python methods.
- Async operations must not evaluate querysets with `list()`, `len()`,
  `bool()`, or synchronous iteration.
- Sync backend APIs remain available for Django compatibility and explicit sync
  execution.

## TDD and verification

Use `SimpleTestCase` for logic that does not require a database and real
integration tests when commits, rollbacks, locks, separate connections, or
concurrency are involved. Run at least the targeted test and affected module;
for the complete backend, also run `unittest discover` and `django check`.

## Tests and benchmarks

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src python -m django check --settings=tests.settings
PYTHONPATH=src python -m tests.mariadb_integration_runner
PYTHONPATH=src python -m tests.benchmark_mariadb
```

The integration and benchmark runners create and automatically remove their
own schemas. Do not run them against a real application database.

Update the README and benchmark whenever the public contract, configuration,
or verification procedure changes. Benchmark numbers must report hardware,
software versions, dataset, iterations, and load.
