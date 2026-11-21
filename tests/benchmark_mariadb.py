"""Compare Django's sync ORM with the native async MariaDB ORM.

The benchmark owns a temporary schema and removes it in ``finally``. It is
not part of the normal unit-test discovery because it requires MariaDB.
"""

import argparse
import asyncio
import importlib.metadata
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    import MySQLdb
except ImportError:
    import pymysql

    pymysql.install_as_MySQLdb()
    import MySQLdb


LIBRARY_ROOT = Path(__file__).resolve().parents[1]


def _dotenv_values():
    values = {}
    env_path = Path(
        os.environ.get(
            "DJANGO_ASYNC_MARIADB_ENV_FILE", LIBRARY_ROOT / ".env"
        )
    )
    if not env_path.exists():
        return values
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def _database_base():
    values = _dotenv_values()
    return {
        "USER": values.get("DB_USER", "root"),
        "PASSWORD": values.get("DB_PASSWORD", ""),
        "HOST": values.get("DB_HOST", "127.0.0.1"),
        "PORT": values.get("DB_PORT", "3306"),
    }


def _database_settings(name, engine):
    settings_dict = _database_base()
    settings_dict.update(
        {
            "ENGINE": engine,
            "NAME": name,
            "OPTIONS": {"charset": "utf8mb4"},
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
            "ATOMIC_REQUESTS": False,
            "TIME_ZONE": None,
            "TEST": {},
        }
    )
    return settings_dict


def _admin_connection():
    values = _database_base()
    return MySQLdb.connect(
        host=values["HOST"],
        port=int(values["PORT"]),
        user=values["USER"],
        password=values["PASSWORD"],
        autocommit=True,
    )


def _create_schema(schema):
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE DATABASE `%s` CHARACTER SET utf8mb4 COLLATE "
                "utf8mb4_unicode_ci" % schema
            )


def _drop_schema(schema):
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS `%s`" % schema)


def _system_command(*args):
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _memory_gib():
    value = _system_command("sysctl", "-n", "hw.memsize")
    if value != "unknown":
        return "%.1f GiB" % (int(value) / 1024**3)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                return "%.1f GiB" % (kib / 1024**2)
    except (OSError, ValueError):
        pass
    return "unknown"


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _print_environment():
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            mariadb_version = cursor.fetchone()[0]
    cpu = _system_command("sysctl", "-n", "machdep.cpu.brand_string")
    if cpu == "unknown":
        cpu = platform.processor() or "unknown"
    print("Environment")
    print("hardware.cpu=%s" % cpu)
    print("hardware.cores=%s" % (os.cpu_count() or "unknown"))
    print("hardware.memory=%s" % _memory_gib())
    print("hardware.os=%s" % platform.platform())
    print("hardware.architecture=%s" % platform.machine())
    print("software.python=%s" % sys.version.split()[0])
    print("software.django=%s" % _package_version("Django"))
    print("software.asyncmy=%s" % _package_version("asyncmy"))
    print("software.mysqlclient=%s" % _package_version("mysqlclient"))
    print("software.pymysql=%s" % _package_version("PyMySQL"))
    print("software.mariadb=%s" % mariadb_version)


def _configure_django(schema):
    import django
    from django.conf import settings

    settings.configure(
        SECRET_KEY="django-async-mariadb-benchmark",
        USE_TZ=True,
        INSTALLED_APPS=["django_async_mariadb"],
        DATABASES={
            "default": _database_settings(
                schema, "django.db.backends.mysql"
            ),
            "async": _database_settings(
                schema, "django_async_mariadb.db.backends.mariadb"
            ),
        },
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    )
    django.setup()


def _define_model():
    from django.db import models

    class BenchmarkRow(models.Model):
        name = models.CharField(max_length=100)
        created_at = models.DateTimeField()
        payload = models.JSONField()
        value = models.DecimalField(max_digits=12, decimal_places=3)

        class Meta:
            app_label = "django_async_mariadb"
            db_table = "async_mariadb_benchmark_row"

    return BenchmarkRow


def _create_table(model):
    from django.db import connections

    with connections["default"].schema_editor() as schema_editor:
        schema_editor.create_model(model)


def _seed(model, count):
    rows = [
        model(
            name="seed-%06d" % index,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            payload={"index": index, "kind": "benchmark"},
            value=Decimal("12.345"),
        )
        for index in range(count)
    ]
    model.objects.using("default").bulk_create(rows, batch_size=500)


def _sync_read(model, limit):
    return list(model.objects.using("default").order_by("id")[:limit])


def _sync_aggregate(model):
    from django.db.models import Avg, Sum

    return model.objects.using("default").aggregate(
        total=Sum("value"), average=Avg("value")
    )


def _sync_insert(model, marker, batch_size):
    model.objects.using("default").bulk_create(
        [
            model(
                name="%s-%04d" % (marker, index),
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                payload={"index": index, "kind": "insert"},
                value=Decimal("3.210"),
            )
            for index in range(batch_size)
        ],
        batch_size=500,
    )


def _sync_delete_marker(model, marker):
    model.objects.using("default").filter(name__startswith=marker).delete()


def _sync_concurrent_read(model, limit, concurrency):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections

    def worker(_index):
        try:
            return len(_sync_read(model, limit))
        finally:
            connections["default"].close()

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        counts = list(executor.map(worker, range(concurrency)))
    elapsed = time.perf_counter() - started
    assert counts == [limit] * concurrency
    return elapsed


def _measure_sync(model, limit, iterations, batch_size):
    results = {}
    _sync_read(model, limit)
    read_samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        rows = _sync_read(model, limit)
        read_samples.append(time.perf_counter() - started)
        assert len(rows) == limit
    results["read"] = read_samples

    _sync_aggregate(model)
    aggregate_samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        aggregate = _sync_aggregate(model)
        aggregate_samples.append(time.perf_counter() - started)
        assert aggregate["total"] is not None
    results["aggregate"] = aggregate_samples

    insert_samples = []
    for index in range(iterations):
        marker = "sync-%d-%s" % (index, uuid.uuid4().hex[:8])
        started = time.perf_counter()
        _sync_insert(model, marker, batch_size)
        insert_samples.append(time.perf_counter() - started)
        _sync_delete_marker(model, marker)
    results["insert"] = insert_samples
    return results


async def _async_read(model, limit):
    queryset = model.async_objects.using("async").order_by("id")[:limit]
    return [row async for row in queryset]


async def _async_aggregate(model):
    from django.db.models import Avg, Sum

    return await model.async_objects.using("async").aaggregate(
        total=Sum("value"), average=Avg("value")
    )


async def _async_insert(model, marker, batch_size):
    await model.async_objects.using("async").abulk_create(
        [
            model(
                name="%s-%04d" % (marker, index),
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                payload={"index": index, "kind": "insert"},
                value=Decimal("3.210"),
            )
            for index in range(batch_size)
        ],
        batch_size=500,
    )


async def _async_delete_marker(model, marker):
    await model.async_objects.using("async").filter(
        name__startswith=marker
    ).adelete()


async def _async_concurrent_read(model, limit, concurrency):
    from django_async_mariadb.db import async_new_connection

    async def worker():
        async with async_new_connection():
            return len(await _async_read(model, limit))

    started = time.perf_counter()
    counts = await asyncio.gather(
        *(worker() for _ in range(concurrency))
    )
    elapsed = time.perf_counter() - started
    assert counts == [limit] * concurrency
    return elapsed


async def _measure_async(model, limit, iterations, batch_size):
    results = {}
    await _async_read(model, limit)
    read_samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        rows = await _async_read(model, limit)
        read_samples.append(time.perf_counter() - started)
        assert len(rows) == limit
    results["read"] = read_samples

    await _async_aggregate(model)
    aggregate_samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        aggregate = await _async_aggregate(model)
        aggregate_samples.append(time.perf_counter() - started)
        assert aggregate["total"] is not None
    results["aggregate"] = aggregate_samples

    insert_samples = []
    for index in range(iterations):
        marker = "async-%d-%s" % (index, uuid.uuid4().hex[:8])
        started = time.perf_counter()
        await _async_insert(model, marker, batch_size)
        insert_samples.append(time.perf_counter() - started)
        await _async_delete_marker(model, marker)
    results["insert"] = insert_samples
    return results


def _milliseconds(samples):
    return statistics.median(samples) * 1000


def _print_results(sync_results, async_results, rows, limit, iterations):
    print("MariaDB ORM benchmark")
    print("rows=%d read_limit=%d iterations=%d" % (rows, limit, iterations))
    print("operation       sync_ms   async_ms   async/sync")
    print("--------------  --------  ---------  ----------")
    for operation in ("read", "aggregate", "insert"):
        sync_ms = _milliseconds(sync_results[operation])
        async_ms = _milliseconds(async_results[operation])
        print(
            "%-14s  %8.3f  %9.3f  %10.3fx"
            % (operation, sync_ms, async_ms, async_ms / sync_ms)
        )


def _parse_load_levels(value):
    try:
        levels = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "load levels must be comma-separated integers"
        ) from exc
    if not levels or min(levels) <= 0:
        raise argparse.ArgumentTypeError(
            "load levels must contain positive integers"
        )
    return levels


def _measure_sync_load(model, limit, levels, iterations):
    measurements = {}
    for level in levels:
        samples = [
            _sync_concurrent_read(model, limit, level)
            for _ in range(iterations)
        ]
        measurements[level] = statistics.median(samples)
    return measurements


async def _measure_async_load(model, limit, levels, iterations):
    measurements = {}
    for level in levels:
        samples = [
            await _async_concurrent_read(model, limit, level)
            for _ in range(iterations)
        ]
        measurements[level] = statistics.median(samples)
    return measurements


def _print_load_results(sync_results, async_results, levels):
    print("\nConcurrent read load")
    print("workers         sync_ms   async_ms   async/sync   sync_rps   async_rps")
    print("--------------  --------  ---------  ----------  ---------  ----------")
    for level in levels:
        sync_ms = sync_results[level] * 1000
        async_ms = async_results[level] * 1000
        print(
            "%-14d  %8.3f  %9.3f  %10.3fx  %9.1f  %10.1f"
            % (
                level,
                sync_ms,
                async_ms,
                async_ms / sync_ms,
                level / sync_results[level],
                level / async_results[level],
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--read-limit", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--load-levels",
        type=_parse_load_levels,
        default=[1, 2, 4, 8],
        help="comma-separated concurrent worker counts",
    )
    parser.add_argument("--load-iterations", type=int, default=3)
    args = parser.parse_args()
    if min(
        args.rows,
        args.read_limit,
        args.iterations,
        args.batch_size,
        args.load_iterations,
    ) <= 0:
        parser.error("all numeric options must be positive")

    schema = "codex_benchmark_%s" % uuid.uuid4().hex[:12]
    _create_schema(schema)
    try:
        _configure_django(schema)
        model = _define_model()
        _create_table(model)
        _seed(model, args.rows)
        _print_environment()
        sync_results = _measure_sync(
            model, args.read_limit, args.iterations, args.batch_size
        )
        async_results = asyncio.run(
            _measure_async(
                model, args.read_limit, args.iterations, args.batch_size
            )
        )
        sync_load_results = _measure_sync_load(
            model,
            args.read_limit,
            args.load_levels,
            args.load_iterations,
        )
        async_load_results = asyncio.run(
            _measure_async_load(
                model,
                args.read_limit,
                args.load_levels,
                args.load_iterations,
            )
        )
        _print_results(
            sync_results,
            async_results,
            args.rows,
            args.read_limit,
            args.iterations,
        )
        _print_load_results(
            sync_load_results,
            async_load_results,
            args.load_levels,
        )
    finally:
        try:
            from django_async_mariadb.db import async_connections

            async_connection = async_connections["async"]
            asyncio.run(async_connection.close())
        except (ImportError, KeyError, RuntimeError):
            pass
        try:
            from django.db import connections

            connections["default"].close()
        except (ImportError, KeyError):
            pass
        _drop_schema(schema)


if __name__ == "__main__":
    main()
