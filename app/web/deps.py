"""Request dependencies. One Store (one sqlite connection) per request, closed afterwards:
sqlite connections are not shared across threads."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.ir.store import Store


def get_store(request: Request) -> Iterator[Store]:
    """FastAPI dependency: `store: Store = Depends(get_store)`. Creates the db on first use."""
    with Store(request.app.state.db_path) as store:
        yield store
