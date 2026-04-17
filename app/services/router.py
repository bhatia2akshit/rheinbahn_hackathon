from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.schemas import ActionType


def select_action(_: list[str]) -> ActionType:
    """Pick a downstream action based on detected categories.

    Current MVP rule: always call police.
    """
    return ActionType.CALL_POLICE


def find_police_department_by_postal_code(
    db: Session,
    postal_code: str,
) -> models.PoliceDepartment | None:
    postal_code_int = int(postal_code)
    stmt = (
        select(models.PoliceDepartment)
        .where(models.PoliceDepartment.postal_code_start <= postal_code_int)
        .where(models.PoliceDepartment.postal_code_end >= postal_code_int)
        .order_by(models.PoliceDepartment.postal_code_start.asc())
        .limit(1)
    )
    return db.scalar(stmt)

