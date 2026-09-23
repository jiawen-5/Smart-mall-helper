from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/platforms")
def platforms(db: Session = Depends(get_db)):
    return db.query(models.Platform).all()


@router.get("/order-status")
def order_status(db: Session = Depends(get_db)):
    return db.query(models.OrderStatus).all()


@router.get("/payment-methods")
def payment_methods(db: Session = Depends(get_db)):
    return db.query(models.PaymentMethod).all()


@router.get("/shipping-methods")
def shipping_methods(db: Session = Depends(get_db)):
    return db.query(models.ShippingMethod).all()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "user_count": db.query(func.count(models.User.global_user_id)).scalar(),
        "product_count": db.query(func.count(models.Product.global_product_id)).scalar(),
        "order_count": db.query(func.count(models.Order.order_id)).scalar(),
        "behavior_count": db.query(func.count(models.UserBehavior.behavior_id)).scalar(),
    }
