from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    emoji = Column(String, default="🙋")


class Habit(Base):
    __tablename__ = "habits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    points = Column(Integer, default=10)
    sort_order = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "key"),)


class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    habit_key = Column(String, nullable=False)
    date = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "habit_key", "date"),)


class Reward(Base):
    __tablename__ = "rewards"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    threshold = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    redeemed_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)


class RedemptionLog(Base):
    __tablename__ = "redemption_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    reward_id = Column(Integer, nullable=False)
    reward_label = Column(String, nullable=False)
    threshold = Column(Integer, nullable=False)
    redeemed_at = Column(DateTime, default=datetime.now)


class PointAdjustment(Base):
    __tablename__ = "point_adjustments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
