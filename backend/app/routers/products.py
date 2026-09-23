from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products(
    keyword: str = "",
    category: str | None = None,
    platform: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(models.Product)
    if keyword:
        q = q.filter(
            or_(
                models.Product.product_name.like(f"%{keyword}%"),
                models.Product.global_product_id.like(f"%{keyword}%"),
                models.Product.brand.like(f"%{keyword}%"),
            )
        )
    if category:
        q = q.filter(models.Product.category == category)
    if platform:
        q = q.filter(models.Product.platform == platform)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    # 每个商品附带真实销量/销售额（order_item 聚合）
    ids = [r.global_product_id for r in rows]
    stats = {}
    if ids:
        for pid, qty, amt in (
            db.query(
                models.OrderItem.global_product_id,
                func.sum(models.OrderItem.quantity),
                func.sum(models.OrderItem.item_total),
            )
            .filter(models.OrderItem.global_product_id.in_(ids))
            .group_by(models.OrderItem.global_product_id)
            .all()
        ):
            stats[pid] = {"sales": int(qty or 0), "revenue": float(amt or 0)}
    return {
        "total": total,
        "items": [
            {
                "global_product_id": r.global_product_id,
                "product_name": r.product_name,
                "category": r.category,
                "subcategory": r.subcategory,
                "platform": r.platform,
                "price": float(r.price or 0),
                "brand": r.brand,
                "stock_status": r.stock_status,
                "tags": r.tags,
                "sales": stats.get(r.global_product_id, {}).get("sales", 0),
                "revenue": stats.get(r.global_product_id, {}).get("revenue", 0),
            }
            for r in rows
        ],
    }


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = db.query(models.Product.category, func.count()).group_by(models.Product.category).all()
    return [{"category": r[0], "count": r[1]} for r in rows]


@router.get("/{pid}")
def detail(pid: str, db: Session = Depends(get_db)):
    p = db.query(models.Product).filter(models.Product.global_product_id == pid).first()
    if not p:
        return {"error": "not found"}
    agg = (
        db.query(func.sum(models.OrderItem.quantity), func.sum(models.OrderItem.item_total))
        .filter(models.OrderItem.global_product_id == pid)
        .one()
    )
    return {
        "product": {
            "global_product_id": p.global_product_id,
            "product_name": p.product_name,
            "category": p.category,
            "price": float(p.price or 0),
            "brand": p.brand,
        },
        "sales": int(agg[0] or 0),
        "revenue": float(agg[1] or 0),
    }
