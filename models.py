from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, UniqueConstraint
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    emoji = Column(String, default="🙋")
    password = Column(String, default="admin123")


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
    claimed = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
