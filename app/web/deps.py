"""Request dependencies. Each request gets its own Store (one sqlite connection), closed
when the response is done; a Store is never shared between concurrent requests."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.ir.store import Store


def get_store(request: Request) -> Iterator[Store]:
    """`store: Store = Depends(get_store)`. Creates the db file if missing: use it only on
    routes that write a project (POST /import)."""
    with Store(request.app.state.db_path) as store:
        yield store


def get_existing_store(request: Request) -> Iterator[Store | None]:
    """`store: Store | None = Depends(get_existing_store)`. Yields None when the db file
    does not exist, and never creates it: use it on read-only pages."""
    path = request.app.state.db_path
    if not path.exists():
        yield None
        return
    with Store(path) as store:
        yield store
