"""Disposable MariaDB integration runner for the async backend.

The runner creates and drops its own schema. It is intentionally not named
``test_*.py`` so the normal unit-test suite never contacts a database.
"""

import asyncio
import os
import uuid
from pathlib import Path

try:
    import MySQLdb
except ImportError:
    import pymysql

    pymysql.install_as_MySQLdb()
    import MySQLdb


LIBRARY_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.conf import settings
from django.db import models
from django.db.models import signals
from django_async_mariadb.db import async_connections, async_new_connection
from django_async_mariadb.db.transaction import async_atomic


class IntegrationRecord(models.Model):
    name = models.CharField(max_length=100)
    happened = models.DateTimeField()
    payload = models.JSONField()
    amount = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        app_label = "django_async_mariadb"
        db_table = "async_integration_record"


class IntegrationChild(models.Model):
    record = models.ForeignKey(
        IntegrationRecord,
        related_name="children",
        on_delete=models.CASCADE,
    )
    label = models.CharField(max_length=100)

    class Meta:
        app_label = "django_async_mariadb"
        db_table = "async_integration_child"


class IntegrationTag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        app_label = "django_async_mariadb"
        db_table = "async_integration_tag"


class IntegrationRecordTag(models.Model):
    record = models.ForeignKey(IntegrationRecord, on_delete=models.CASCADE)
    tag = models.ForeignKey(IntegrationTag, on_delete=models.CASCADE)
    note = models.CharField(max_length=100)

    class Meta:
        app_label = "django_async_mariadb"
        db_table = "async_integration_record_tag"
        constraints = [
            models.UniqueConstraint(
                fields=("record", "tag"),
                name="async_integration_record_tag_unique",
            )
        ]


IntegrationRecord.add_to_class(
    "tags",
    models.ManyToManyField(
        IntegrationTag,
        through=IntegrationRecordTag,
        related_name="records",
    ),
)


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


def _database_settings(name):
    values = _dotenv_values()
    options = {"charset": "utf8mb4"}
    if os.environ.get("ASYNC_MARIADB_POOL") == "1":
        options["pool"] = {"minsize": 1, "maxsize": 4}
    return {
        "ENGINE": "django_async_mariadb.db.backends.mariadb",
        "NAME": name,
        "USER": values.get("DB_USER", "root"),
        "PASSWORD": values.get("DB_PASSWORD", ""),
        "HOST": values.get("DB_HOST", "127.0.0.1"),
        "PORT": values.get("DB_PORT", "3306"),
        "OPTIONS": options,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
        "TIME_ZONE": None,
        "TEST": {},
    }


def _admin_connection():
    values = _dotenv_values()
    return MySQLdb.connect(
        host=values.get("DB_HOST", "127.0.0.1"),
        port=int(values.get("DB_PORT", "3306")),
        user=values.get("DB_USER", "root"),
        password=values.get("DB_PASSWORD", ""),
        autocommit=True,
    )


def _create_schema(name):
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE DATABASE `%s` CHARACTER SET utf8mb4 COLLATE "
                "utf8mb4_unicode_ci" % name
            )


def _drop_schema(name):
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS `%s`" % name)


async def _create_tables(connection):
    statements = [
        """CREATE TABLE async_integration_record (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            happened DATETIME(6) NOT NULL,
            payload JSON NOT NULL,
            amount DECIMAL(12, 3) NOT NULL
        ) ENGINE=InnoDB""",
        """CREATE TABLE async_integration_child (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            record_id BIGINT NOT NULL,
            label VARCHAR(100) NOT NULL,
            CONSTRAINT async_integration_child_record_fk
                FOREIGN KEY (record_id)
                REFERENCES async_integration_record (id)
        ) ENGINE=InnoDB""",
        """CREATE TABLE async_integration_tag (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE
        ) ENGINE=InnoDB""",
        """CREATE TABLE async_integration_record_tag (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            record_id BIGINT NOT NULL,
            tag_id BIGINT NOT NULL,
            note VARCHAR(100) NOT NULL,
            CONSTRAINT async_integration_record_tag_record_fk
                FOREIGN KEY (record_id)
                REFERENCES async_integration_record (id),
            CONSTRAINT async_integration_record_tag_tag_fk
                FOREIGN KEY (tag_id)
                REFERENCES async_integration_tag (id),
            CONSTRAINT async_integration_record_tag_unique
                UNIQUE (record_id, tag_id)
        ) ENGINE=InnoDB""",
    ]
    async with await connection.cursor() as cursor:
        for statement in statements:
            await cursor.execute(statement)


async def _drop_tables(connection):
    async with await connection.cursor() as cursor:
        for table in (
            "async_integration_record_tag",
            "async_integration_child",
            "async_integration_tag",
            "async_integration_record",
        ):
            await cursor.execute("DROP TABLE IF EXISTS %s" % table)


async def _run():
    schema = "codex_async_%s" % uuid.uuid4().hex[:12]
    # The integration case exercises timezone-aware MariaDB datetime values.
    settings.USE_TZ = True
    settings.DATABASES["default"] = _database_settings(schema)
    connection = async_connections["default"]
    completed = []
    try:
        _create_schema(schema)
        await _create_tables(connection)
        completed.append("schema")

        record = await IntegrationRecord.async_objects.acreate(
            name="first",
            happened="2026-01-02T03:04:05.123456Z",
            payload={"kind": "json", "items": [1, 2]},
            amount="12.345",
        )
        fresh = await IntegrationRecord.async_objects.aget(pk=record.pk)
        assert fresh.payload == {"kind": "json", "items": [1, 2]}
        assert str(fresh.amount) == "12.345"
        assert fresh.happened.year == 2026
        record.name = "changed"
        await record.arefresh_from_db(fields=["name"])
        assert record.name == "first"
        record.name = "changed-again"
        await record.arefresh_from_db(
            from_queryset=IntegrationRecord._default_manager.all()
        )
        assert record.name == "first"
        completed.append("create-refresh-json-date-decimal")

        await IntegrationChild.async_objects.acreate(
            record=record, label="child"
        )
        assert await record.children.acount() == 1
        completed.append("reverse-related")

        selected = await IntegrationChild.async_objects.select_related(
            "record"
        ).aget(label="child")
        assert selected.record.pk == record.pk
        completed.append("select-related")

        tag = await IntegrationTag.async_objects.acreate(name="tag")
        signal_actions = []

        async def m2m_receiver(**kwargs):
            signal_actions.append(kwargs["action"])

        signals.m2m_changed.connect(
            m2m_receiver,
            sender=IntegrationRecordTag,
            weak=False,
        )
        await record.tags.aadd(tag, through_defaults={"note": "native"})
        assert await record.tags.acount() == 1
        through = await IntegrationRecordTag.async_objects.aget(
            record_id=record.pk, tag_id=tag.pk
        )
        assert through.note == "native"
        await record.tags.aremove(tag)
        assert await record.tags.acount() == 0
        await record.tags.aadd(tag, through_defaults={"note": "set"})
        await record.tags.aset([], clear=False)
        assert await record.tags.acount() == 0
        await record.tags.aclear()
        assert signal_actions == [
            "pre_add",
            "post_add",
            "pre_remove",
            "post_remove",
            "pre_add",
            "post_add",
            "pre_remove",
            "post_remove",
            "pre_clear",
            "post_clear",
        ]
        signals.m2m_changed.disconnect(
            m2m_receiver,
            sender=IntegrationRecordTag,
        )
        completed.append("m2m-through-writes")

        calls = []
        async with async_atomic():
            committed = await IntegrationRecord.async_objects.acreate(
                name="committed",
                happened="2026-01-02T03:04:05Z",
                payload={},
                amount="1.000",
            )
            await connection.on_commit(lambda: calls.append("committed"))
        assert await IntegrationRecord.async_objects.filter(
            pk=committed.pk
        ).aexists()
        assert calls == ["committed"]

        try:
            async with async_atomic():
                await IntegrationRecord.async_objects.acreate(
                    name="rolled-back",
                    happened="2026-01-02T03:04:05Z",
                    payload={},
                    amount="2.000",
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        assert not await IntegrationRecord.async_objects.filter(
            name="rolled-back"
        ).aexists()

        try:
            async with async_atomic():
                async with async_atomic():
                    await IntegrationRecord.async_objects.acreate(
                        name="savepoint-rolled-back",
                        happened="2026-01-02T03:04:05Z",
                        payload={},
                        amount="3.000",
                    )
                    raise RuntimeError("savepoint")
        except RuntimeError:
            pass
        assert not await IntegrationRecord.async_objects.filter(
            name="savepoint-rolled-back"
        ).aexists()
        completed.append("commit-rollback-savepoint-on-commit")

        async with async_atomic():
            locked = await IntegrationRecord.async_objects.select_for_update().aget(
                pk=record.pk
            )
            assert locked.pk == record.pk
        completed.append("select-for-update")

        if os.environ.get("ASYNC_MARIADB_POOL") == "1":
            async def isolated_count():
                async with async_new_connection():
                    return await IntegrationRecord.async_objects.acount()

            counts = await asyncio.gather(
                isolated_count(), isolated_count(), isolated_count()
            )
            assert counts == [2, 2, 2]
            completed.append("pool-concurrency")

        await connection.close()
        if os.environ.get("ASYNC_MARIADB_POOL") == "1":
            await async_connections["default"].close_pool()
        connection = None
        completed.append("connection-close")
        return completed
    finally:
        if connection is not None:
            await connection.close()
        _drop_schema(schema)


def main():
    result = asyncio.run(asyncio.wait_for(_run(), timeout=30))
    print("integration_ok=" + ",".join(result), flush=True)


if __name__ == "__main__":
    main()
