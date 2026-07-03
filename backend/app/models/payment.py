from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    razorpay_sub_id = Column(String, unique=True)
    plan_name = Column(String)
    status = Column(String)
    starts_at = Column(DateTime(timezone=True))
    ends_at = Column(DateTime(timezone=True))

class Payment(Base):
    __tablename__ = "payments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    razorpay_order_id = Column(String, unique=True)
    razorpay_payment_id = Column(String)
    amount_paise = Column(Integer)
    currency = Column(String, default="INR")
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
