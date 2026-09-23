from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("")
def list_orders(
    status: str | None = None,
    platform: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(models.Order).order_by(models.Order.order_time.desc())
    if status:
        q = q.filter(models.Order.order_status == status)
    if platform:
        q = q.filter(models.Order.platform == platform)
    total = q.count()
    return {"total": total, "items": q.offset((page - 1) * page_size).limit(page_size).all()}


@router.get("/health")
def health(platform: str | None = None, days: int = 7, db: Session = Depends(get_db)):
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days if days > 0 else 7)
    q = db.query(models.Order.order_status, func.count()).filter(models.Order.order_time >= cutoff)
    if platform:
        q = q.filter(models.Order.platform == platform)
    rows = q.group_by(models.Order.order_status).order_by(func.count().desc()).all()
    total = sum(r[1] for r in rows) or 1
    return [{"status": r[0], "count": r[1], "pct": round(r[1] / total * 100, 1)} for r in rows]


@router.get("/{order_id}")
def detail(order_id: str, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.order_id == order_id).first()
    items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).all()
    return {"order": order, "items": items}
