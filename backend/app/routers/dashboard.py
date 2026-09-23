from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _range_days(range_: str) -> int:
    return {"7d": 7, "15d": 15, "30d": 30}.get(range_, 7)


@router.get("/metrics")
def metrics(platform: str | None = None, db: Session = Depends(get_db)):
    """今日销售额 / 订单数 / 活跃用户 / 转化率：全部从 order + user_behavior 实时算."""
    today = datetime.now().date()
    qo = db.query(
        func.coalesce(func.sum(models.Order.total_amount), 0).label("sales"),
        func.count(models.Order.order_id).label("orders"),
    ).filter(func.date(models.Order.order_time) == today)
    qb = db.query(func.count(func.distinct(models.UserBehavior.global_user_id))).filter(
        func.date(models.UserBehavior.behavior_time) == today
    )
    if platform:
        qo = qo.filter(models.Order.platform == platform)
        qb = qb.filter(models.UserBehavior.platform == platform)
    sales, orders = qo.one().sales, qo.one().orders
    dau = qb.scalar() or 0
    return {
        "today_sales": float(sales or 0),
        "today_orders": int(orders or 0),
        "active_users": int(dau),
        "conversion_rate": round((orders / dau * 100) if dau else 0, 2),
    }


@router.get("/trend")
def trend(
    range_: str = Query("7d", alias="range"),
    platform: str | None = None,
    db: Session = Depends(get_db),
):
    days = _range_days(range_)
    start = datetime.now().date() - timedelta(days=days - 1)
    q = (
        db.query(
            func.date(models.Order.order_time).label("d"),
            func.coalesce(func.sum(models.Order.total_amount), 0).label("sales"),
            func.count(models.Order.order_id).label("orders"),
        )
        .filter(func.date(models.Order.order_time) >= start)
    )
    if platform:
        q = q.filter(models.Order.platform == platform)
    rows = {str(r.d): (float(r.sales), int(r.orders)) for r in q.group_by("d").all()}
    dates, sales, orders = [], [], []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        dates.append(d[5:])
        s, o = rows.get(str(start + timedelta(days=i)), (0.0, 0))
        sales.append(round(s / 10000, 2))
        orders.append(o)
    return {"dates": dates, "sales": sales, "orders": orders}


@router.get("/funnel")
def funnel(platform: str | None = None, db: Session = Depends(get_db)):
    """转化漏斗：浏览→加购→下单→支付，用 behavior_type 分组计数."""
    q = db.query(models.UserBehavior.behavior_type, func.count()).group_by(
        models.UserBehavior.behavior_type
    )
    if platform:
        q = q.filter(models.UserBehavior.platform == platform)
    return [{"behavior_type": r[0], "count": r[1]} for r in q.all()]
