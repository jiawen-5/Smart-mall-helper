"""SQLAlchemy 模型：表名与字段严格对应用户 MySQL 真实表."""
from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Numeric, Text, String
from .database import Base


class Platform(Base):
    __tablename__ = "platform"
    code = Column(String(20), primary_key=True)
    name = Column(String(50))
    description = Column(String(200))


class OrderStatus(Base):
    __tablename__ = "order_status"
    code = Column(String(20), primary_key=True)
    name = Column(String(50))
    badge_class = Column(String(50))
    description = Column(String(200))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class PaymentMethod(Base):
    __tablename__ = "payment_method"
    code = Column(String(20), primary_key=True)
    name = Column(String(50))
    description = Column(String(200))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class ShippingMethod(Base):
    __tablename__ = "shipping_method"
    code = Column(String(20), primary_key=True)
    name = Column(String(50))
    description = Column(String(200))


class User(Base):
    __tablename__ = "user"
    global_user_id = Column(String(50), primary_key=True)
    platform_user_id = Column(String(50))
    platform = Column(String(20), index=True)
    user_name = Column(String(50))
    gender = Column(String(1))
    age = Column(Integer)
    city = Column(String(50))
    registration_date = Column(Date)
    phone = Column(String(20), index=True)
    email = Column(String(100), index=True)
    user_level = Column(String(20))


class Product(Base):
    __tablename__ = "product"
    global_product_id = Column(String(50), primary_key=True)
    platform_product_id = Column(String(50))
    platform = Column(String(20), index=True)
    product_name = Column(String(200), index=True)
    category = Column(String(50), index=True)
    subcategory = Column(String(50))
    price = Column(Numeric(10, 2))
    brand = Column(String(100))
    stock_status = Column(String(20))
    tags = Column(Text)


class UserBehavior(Base):
    __tablename__ = "user_behavior"
    behavior_id = Column(Integer, primary_key=True, autoincrement=True)
    global_user_id = Column(String(50), index=True)
    global_product_id = Column(String(50))
    platform = Column(String(20), index=True)
    session_id = Column(String(100))
    behavior_type = Column(String(50), index=True)
    behavior_time = Column(DateTime, index=True)
    duration_seconds = Column(Integer)
    page_url = Column(String(500))
    referrer = Column(String(500))
    device_type = Column(String(50))
    app_version = Column(String(50))
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    extra_data = Column(Text)


class Order(Base):
    __tablename__ = "order"
    order_id = Column(String(100), primary_key=True)
    global_user_id = Column(String(50), index=True)
    platform = Column(String(20), index=True)
    order_time = Column(DateTime, index=True)
    payment_time = Column(DateTime)
    payment_method = Column(String(50))
    shipping_address = Column(Text)
    order_status = Column(String(50), index=True)
    total_amount = Column(Numeric(12, 2))
    discount_amount = Column(Numeric(10, 2))
    shipping_fee = Column(Numeric(8, 2))
    tax_amount = Column(Numeric(8, 2))
    promotion_id = Column(String(100))
    coupon_code = Column(String(50))
    shipping_method = Column(String(50))


class OrderItem(Base):
    __tablename__ = "order_item"
    order_item_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), index=True)
    global_product_id = Column(String(50), index=True)
    quantity = Column(Integer)
    unit_price = Column(Numeric(10, 2))
    item_total = Column(Numeric(12, 2))
    sku_info = Column(Text)
