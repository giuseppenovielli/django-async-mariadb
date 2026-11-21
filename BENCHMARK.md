# Sync vs. Async ORM Benchmark

This benchmark compares Django's synchronous ORM path with the native async
ORM path of `django_async_mariadb` on the same MariaDB server and dataset.

The test creates a temporary `codex_benchmark_*` schema, uses it for the entire
measurement, and always removes it in the `finally` block. The application
database is not used or modified.

## Running the benchmark

From the project directory, using a virtual environment that contains Django,
`asyncmy`, and PyMySQL:

```bash
PYTHONPATH=. python -m tests.benchmark_mariadb
```

Available options:

```text
--rows N          initial dataset rows, default 5000
--read-limit N    rows materialized during reads, default 1000
--iterations N    repetitions per operation, default 7
--batch-size N    rows per bulk insert, default 500
--load-levels     separate concurrent workers, default 1,2,4,8
--load-iterations repetitions per load level, default 3
```

The runner reads the host, port, user, and password from the library's `.env`,
environment variables, or the file specified by
`DJANGO_ASYNC_MARIADB_ENV_FILE`; it contains no hardcoded credentials.

## Compared operations

- `read`: materialization of ORM objects with `order_by()` and a limit;
- `aggregate`: `Sum` and `Avg` on a `DecimalField`;
- `insert`: batch insertion with `bulk_create()` versus `abulk_create()`.

The `Concurrent read load` section runs one read per worker. The sync ORM uses
separate threads, while the async ORM uses separate tasks and
`async_new_connection()`, so no task illegally shares the same connection. It
reports both the group's total latency and throughput in requests per second.

A warm-up runs before measurement. The reported result is the median of the
samples; `async/sync < 1.0x` means the async path is faster, while `> 1.0x`
means it is slower for that individual query. The benchmark measures both ORM
path latency and the ability to interleave multiple concurrent I/O operations
in the same event loop.

## Measurement environment

Run on November 19, 2026:

```text
hardware.cpu=Apple M2
hardware.cores=8
hardware.memory=24.0 GiB
hardware.os=macOS-15.7.3-arm64-arm-64bit-Mach-O
hardware.architecture=arm64
software.python=3.13.18
software.django=5.2.18
software.asyncmy=0.2.13
software.pymysql=1.1.2
software.mariadb=10.7.8-MariaDB
```

## Local result

The run used 5,000 rows, a read limit of 1,000, 7 iterations, a 500-row insert
batch, and 5 iterations per concurrency level:

```text
operation       sync_ms   async_ms   async/sync
--------------  --------  ---------  ----------
read               8.924      6.811       0.763x
aggregate          2.518      2.161       0.858x
insert            14.933     13.501       0.904x
```

In this run, the async path was approximately 23.7% faster for reads, 14.2%
faster for aggregation, and 9.6% faster for batch inserts.

Concurrent load for reading 1,000 objects, without a shared pool and with one
isolated connection per async worker:

```text
workers         sync_ms   async_ms   async/sync   sync_rps   async_rps
--------------  --------  ---------  ----------  ---------  ----------
1                 10.882      9.053       0.832x       91.9       110.5
2                 22.989     14.951       0.650x       87.0       133.8
4                 62.618     26.120       0.417x       63.9       153.1
8                125.285     49.697       0.397x       63.9       161.0
```

With 8 workers, measured async throughput was approximately 2.5 times the sync
throughput. This result applies to this hardware, load, and local connections;
it is not a general performance guarantee.

The numbers depend on CPU, server load, network, driver, and dataset size; they
must not be interpreted as a general performance guarantee.
