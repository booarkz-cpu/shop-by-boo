"""One way to page lists of the API (v28.59.0, stage 5).

``limit`` and ``offset`` come as query parameters; the response keeps its old shape (a list or the
same object), and the total number of rows is sent in the ``X-Total-Count`` header. Old clients that
do not page get the first ``DEFAULT_LIMIT`` rows — the newest first — instead of the whole table.

    @router.get("/api/admin/things")
    async def things(response: Response, page: Page = Depends(page_params), db=...):
        stmt = select(Thing).order_by(Thing.id.desc())
        await set_total(response, db, stmt)
        rows = (await db.execute(page.apply(stmt))).scalars().all()
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 500
MAX_LIMIT = 1000


@dataclass(frozen=True)
class Page:
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def apply(self, stmt):
        return stmt.limit(self.limit).offset(self.offset)


def page_params(limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Сколько строк вернуть"),
                offset: int = Query(0, ge=0, le=10_000_000, description="Сколько строк пропустить")) -> Page:
    return Page(limit=limit, offset=offset)


async def set_total(response: Response, db: AsyncSession, stmt) -> int:
    """Count the rows of ``stmt`` (ordering removed) and expose the total to the client."""
    total = int(await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    response.headers["X-Total-Count"] = str(total)
    return total
