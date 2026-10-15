from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def paginate(
    session: AsyncSession, stmt: Select[T], page: int, size: int
) -> tuple[list[T], int]:
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * size).limit(size))).scalars()
    return list(rows), int(total)


def apply_updates(obj: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(obj, key, value)
