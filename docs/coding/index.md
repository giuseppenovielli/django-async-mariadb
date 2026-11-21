# Development rules

This documentation contains the rules that apply to the
`django-async-mariadb` library.

## Technical scope

- Python `>=3.10`.
- Django `>=5.2,<6.0`.
- MariaDB 10.11 as the primary target.
- Async driver `asyncmy >=0.2,<0.3`.
- Supporting sync driver PyMySQL `>=1.1,<2`.
- Async path usable with ASGI.

The package is a Django backend specialized for MariaDB. The async path uses
`asyncmy` and must not introduce `sync_to_async` to perform ORM I/O. The sync
path remains available for compatibility with Django, the admin, migrations,
and management commands.

## General rules

- Keep changes small, readable, and focused.
- Reuse existing utilities before introducing new abstractions.
- Do not depend on a host Django project.
- Do not place credentials, tokens, or local data in versioned files.
- Keep the backend, connections, ORM, transactions, and tests separated.
- Document every change to the public contract, configuration, or verification
  procedure.

## Specific documents

- [Testing and TDD](testing.md): methodology, commands, and MariaDB tests.
- [Django and MariaDB](django.md): ORM, backend, and connection compatibility.

## Minimum verification

Before delivering a change, run the following when the environment allows it:

```bash
.venv/bin/python -m django check --settings=tests.settings
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

For changes to the database path, also run the real MariaDB runner and
explicitly report the environment, server version, and results.
