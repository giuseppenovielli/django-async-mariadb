from django.db.models.manager import BaseManager

from django_async_mariadb.db.models.query import QuerySet


class AsyncManager(BaseManager.from_queryset(QuerySet)):
    pass
