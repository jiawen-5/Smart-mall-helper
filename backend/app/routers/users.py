from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/segments")
def segments(platform: str | None = None, db: Session = Depends(get_db)):
    """按 user_level 分层；行为频次分布按人均行为数划分高/中/低频."""
    q = db.query(models.User.user_level, func.count()).group_by(models.User.user_level)
    if platform:
        q = q.filter(models.User.platform == platform)
    levels = [{"user_level": r[0], "count": r[1]} for r in q.all()]
    sub = (
        db.query(
            models.UserBehavior.global_user_id,
            func.count().label("c"),
        )
        .group_by(models.UserBehavior.global_user_id)
        .subquery()
    )
    fq = db.query(sub.c.c).all()
    high = sum(1 for (c,) in fq if c >= 20)
    mid = sum(1 for (c,) in fq if 5 <= c < 20)
    low = sum(1 for (c,) in fq if c < 5)
    return {"levels": levels, "frequency": {"高频": high, "中频": mid, "低频": low}}


@router.get("")
def list_users(
    keyword: str = "",
    platform: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(models.User)
    if keyword:
        q = q.filter(
            (models.User.user_name.like(f"%{keyword}%"))
            | (models.User.global_user_id.like(f"%{keyword}%"))
            | (models.User.phone.like(f"%{keyword}%"))
        )
    if platform:
        q = q.filter(models.User.platform == platform)
    total = q.count()
    return {"total": total, "items": q.offset((page - 1) * page_size).limit(page_size).all()}
