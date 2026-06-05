import os
import logging
import calendar
import hashlib
import secrets
from typing import Optional
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, text
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from database import init_db, get_db, SessionLocal
from models import User, Habit, Record, Reward, RedemptionLog, PointAdjustment, Broadcast

DEFAULT_USERS = [("me", "我", "🙋"), ("wife", "女王大人", "👑")]
ALL_USERS = [uid for uid, _, _ in DEFAULT_USERS]
CONFIG_USER_ID = DEFAULT_USERS[0][0]

app = FastAPI(title="✨ 小进步")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sync_shared_habit_config(db: Session):
    """Keep habit labels, points and order shared across the two users."""
    source_habits = db.query(Habit).filter(
        Habit.user_id == CONFIG_USER_ID
    ).order_by(Habit.sort_order).all()
    source_keys = {h.key for h in source_habits}

    for uid in ALL_USERS:
        if uid == CONFIG_USER_ID:
            continue
        for source in source_habits:
            target = db.query(Habit).filter(
                Habit.user_id == uid, Habit.key == source.key
            ).first()
            if target:
                target.label = source.label
                target.points = source.points
                target.sort_order = source.sort_order
            else:
                db.add(Habit(
                    user_id=uid,
                    key=source.key,
                    label=source.label,
                    points=source.points,
                    sort_order=source.sort_order,
                ))

        extra_habits = db.query(Habit).filter(
            Habit.user_id == uid,
            Habit.key.notin_(source_keys),
        ).all()
        for habit in extra_habits:
            db.query(Record).filter(
                Record.user_id == uid,
                Record.habit_key == habit.key,
            ).delete()
            db.delete(habit)


def _sync_shared_reward_config(db: Session):
    """Mirror the primary user's reward list for the other user."""
    source_rewards = db.query(Reward).filter(
        Reward.user_id == CONFIG_USER_ID
    ).order_by(Reward.sort_order, Reward.threshold).all()

    for order, source in enumerate(source_rewards):
        source.sort_order = order

    for uid in ALL_USERS:
        if uid == CONFIG_USER_ID:
            continue
        target_rewards = db.query(Reward).filter(Reward.user_id == uid).all()
        targets_by_order = {reward.sort_order: reward for reward in target_rewards}
        source_orders = {source.sort_order for source in source_rewards}

        for source in source_rewards:
            target = targets_by_order.get(source.sort_order)
            if target:
                target.threshold = source.threshold
                target.label = source.label
                target.sort_order = source.sort_order
            else:
                db.add(Reward(
                    user_id=uid,
                    threshold=source.threshold,
                    label=source.label,
                    redeemed_count=0,
                    sort_order=source.sort_order,
                ))

        for reward in target_rewards:
            if reward.sort_order not in source_orders and reward.redeemed_count == 0:
                db.delete(reward)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()

    # Migrate: add redeemed_count column, migrate claimed → redeemed_count
    from sqlalchemy import inspect
    inspector = inspect(db.bind)
    columns = {c["name"] for c in inspector.get_columns("rewards")}
    if "claimed" in columns and "redeemed_count" not in columns:
        db.execute(text("ALTER TABLE rewards ADD COLUMN redeemed_count INTEGER DEFAULT 0"))
        db.execute(text("UPDATE rewards SET redeemed_count = 1 WHERE claimed = 1"))
        db.commit()
        logger.info("Migrated rewards: claimed → redeemed_count")

    # Ensure new tables exist
    from database import Base as DBBase
    DBBase.metadata.create_all(bind=db.bind, tables=[
        RedemptionLog.__table__,
        PointAdjustment.__table__,
        Broadcast.__table__,
    ])

    for uid, name, emoji in DEFAULT_USERS:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            db.add(User(id=uid, display_name=name, emoji=emoji))
        else:
            # Update existing users to keep display names current
            user.display_name = name
            user.emoji = emoji
    default_habits = [
        ("water", "💧 喝水 1.5L", 10, 0),
        ("exercise", "🏃 运动 20分钟", 15, 1),
        ("nophone", "📱 22:30前放下手机", 10, 2),
        ("sugar", "🍬 控糖", 10, 3),
        ("baby", "👶 陪宝宝 30-60分钟", 15, 4),
        ("nophonemeal", "🍽️ 吃饭不玩手机", 5, 5),
    ]
    for uid, _, _ in DEFAULT_USERS:
        for key, label, pts, order in default_habits:
            if not db.query(Habit).filter(Habit.user_id == uid, Habit.key == key).first():
                db.add(Habit(user_id=uid, key=key, label=label, points=pts, sort_order=order))
    default_rewards = [
        (50, "🍵 一杯想喝的饮品", 0),
        (100, "🍦 一起吃个冰淇淋", 1),
        (200, "🎲 一起玩桌游/游戏之夜", 2),
        (350, "🛀 一次放松SPA时光", 3),
        (500, "🍽️ 去一家想去的餐厅", 4),
        (750, "🛍️ 买一件喜欢的衣服", 5),
        (1000, "🏕️ 周末短途旅行", 6),
        (1500, "🎁 一个心愿礼物", 7),
    ]
    for uid, _, _ in DEFAULT_USERS:
        for thresh, label, order in default_rewards:
            if not db.query(Reward).filter(Reward.user_id == uid, Reward.threshold == thresh).first():
                db.add(Reward(user_id=uid, threshold=thresh, label=label, sort_order=order))
    _sync_shared_habit_config(db)
    _sync_shared_reward_config(db)
    db.commit()
    db.close()


# ── Pydantic models ──

class LoginRequest(BaseModel):
    user_id: str
    code: str = ""

class HabitCreate(BaseModel):
    user_id: str
    key: str
    label: str
    points: int = Field(default=10, gt=0, le=1000)
    sort_order: Optional[int] = 0

class ToggleRequest(BaseModel):
    user_id: str
    habit_key: str

class RewardCreate(BaseModel):
    user_id: str
    threshold: int
    label: str

class ClaimRequest(BaseModel):
    user_id: str
    reward_id: int

class AdjustPointsRequest(BaseModel):
    user_id: str
    amount: int
    reason: str

class BroadcastRequest(BaseModel):
    user_id: str
    content: str = Field(..., max_length=200)

class AdminLogin(BaseModel):
    password: str

class ReorderItem(BaseModel):
    key: str
    sort_order: int

class ReorderRequest(BaseModel):
    habits: list[ReorderItem]

class RewardReorderItem(BaseModel):
    id: int
    sort_order: int

class RewardReorderRequest(BaseModel):
    rewards: list[RewardReorderItem]


# ── Admin auth / Access code ──

ADMIN_PASSWORD = os.environ.get("MB_ADMIN_PASSWORD", "admin123")
ACCESS_CODE = os.environ.get("MB_ACCESS_CODE", "love2024")


def _admin_token():
    configured = os.environ.get("MB_ADMIN_TOKEN")
    if configured:
        return configured
    return hashlib.sha256(
        f"{ADMIN_PASSWORD}:little-progress-admin".encode("utf-8")
    ).hexdigest()


def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    expected = _admin_token()
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(403, "Admin authentication required")


# ── User / Habits ──

@app.post("/api/login")
def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    if req.code != ACCESS_CODE:
        raise HTTPException(403, "访问码错误")
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    habits = db.query(Habit).filter(Habit.user_id == req.user_id).order_by(Habit.sort_order).all()
    rewards = db.query(Reward).filter(
        Reward.user_id == req.user_id
    ).order_by(Reward.sort_order, Reward.threshold).all()
    today = date.today().isoformat()
    today_records = db.query(Record).filter(
        Record.user_id == req.user_id, Record.date == today
    ).all()
    return {
        "user": {"id": user.id, "display_name": user.display_name, "emoji": user.emoji},
        "habits": [
            {"key": h.key, "label": h.label, "points": h.points, "sort_order": h.sort_order}
            for h in habits
        ],
        "rewards": [
            {
                "id": r.id,
                "threshold": r.threshold,
                "label": r.label,
                "redeemed_count": r.redeemed_count,
                "sort_order": r.sort_order,
            }
            for r in rewards
        ],
        "today_records": {r.habit_key: True for r in today_records},
    }


@app.get("/api/habits")
def get_habits(user_id: str, db: Session = Depends(get_db)):
    habits = db.query(Habit).filter(Habit.user_id == user_id).order_by(Habit.sort_order).all()
    return [
        {"key": h.key, "label": h.label, "points": h.points, "sort_order": h.sort_order}
        for h in habits
    ]


@app.post("/api/habits")
def create_habit(
    req: HabitCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    for uid in ALL_USERS:
        existing = db.query(Habit).filter(
            Habit.user_id == uid, Habit.key == req.key
        ).first()
        if existing:
            existing.label = req.label
            existing.points = req.points
            existing.sort_order = req.sort_order
        else:
            db.add(Habit(
                user_id=uid, key=req.key,
                label=req.label, points=req.points,
                sort_order=req.sort_order,
            ))
    db.commit()
    return {"status": "ok"}


@app.delete("/api/habits/{key}")
def delete_habit(
    key: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    for uid in ALL_USERS:
        db.query(Record).filter(
            Record.user_id == uid, Record.habit_key == key
        ).delete()
        db.query(Habit).filter(
            Habit.user_id == uid, Habit.key == key
        ).delete()
    db.commit()
    return {"status": "ok"}


@app.put("/api/habits/reorder")
def reorder_habits(
    req: ReorderRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    for uid in ALL_USERS:
        for item in req.habits:
            habit = db.query(Habit).filter(
                Habit.user_id == uid, Habit.key == item.key
            ).first()
            if habit:
                habit.sort_order = item.sort_order
    db.commit()
    return {"status": "ok"}


# ── Records ──

@app.post("/api/toggle")
def toggle_habit(req: ToggleRequest, db: Session = Depends(get_db)):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        record = db.query(Record).filter(
            Record.user_id == req.user_id,
            Record.habit_key == req.habit_key,
            Record.date == today,
        ).first()
        if record:
            db.delete(record)
            msg = "deleted"
        else:
            db.add(Record(user_id=req.user_id, habit_key=req.habit_key, date=today))
            msg = "created"
            habit = db.query(Habit).filter(
                Habit.user_id == req.user_id, Habit.key == req.habit_key
            ).first()
            if habit:
                db.add(Broadcast(
                    user_id=req.user_id,
                    type="auto",
                    content=f"完成了 {habit.label}",
                ))
        db.commit()
        logger.info(f"Toggle {req.user_id}/{req.habit_key}: {msg}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Toggle failed: {e}")
        db.rollback()
        raise HTTPException(500, str(e))


@app.get("/api/records/month")
def get_month_records(user_id: str, year: int, month: int, db: Session = Depends(get_db)):
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"
    records = db.query(Record).filter(
        Record.user_id == user_id,
        Record.date >= start_date,
        Record.date <= end_date,
    ).all()
    habits = {h.key: h.points for h in db.query(Habit).filter(Habit.user_id == user_id).all()}

    result = {}
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        date_str = f"{year}-{month:02d}-{d:02d}"
        day_list = [(r.habit_key, True) for r in records if r.date == date_str]
        day_records = dict(day_list)
        day_points = sum(habits.get(k, 0) for k in day_records)
        result[date_str] = {
            "done_count": len(day_records),
            "points": day_points,
            "habits": day_records,
        }
    return result


@app.delete("/api/records")
def clear_records(user_id: str, db: Session = Depends(get_db)):
    """Clear all records for a single user (does not delete habits or rewards)."""
    db.query(Record).filter(Record.user_id == user_id).delete()
    db.commit()
    return {"status": "ok"}


@app.get("/api/week-stats")
def get_week_stats(user_id: str, db: Session = Depends(get_db)):
    return _calc_weekly_stats(user_id, db)


# ── Points & Rewards ──

def _calc_points(user_id: str, db: Session):
    total_raw = db.query(
        func.coalesce(func.sum(Habit.points), 0)
    ).select_from(Record).join(
        Habit,
        and_(Record.habit_key == Habit.key, Record.user_id == Habit.user_id)
    ).filter(Record.user_id == user_id).scalar()
    rewards = db.query(Reward).filter(Reward.user_id == user_id).all()
    redeemed = sum(r.threshold * r.redeemed_count for r in rewards)
    weekly = _calc_weekly_stats(user_id, db)
    bonus = 30 if weekly["pct"] >= 70 else 0
    adjustments = db.query(
        func.coalesce(func.sum(PointAdjustment.amount), 0)
    ).filter(PointAdjustment.user_id == user_id).scalar()
    return total_raw, bonus, redeemed, total_raw + bonus - redeemed + adjustments


def _calc_weekly_stats(user_id: str, db: Session):
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_start = datetime(week_start.year, week_start.month, week_start.day)
    habit_keys = [h.key for h in db.query(Habit).filter(Habit.user_id == user_id).all()]
    total_possible = len(habit_keys)
    week_done = 0
    for i in range(7):
        d = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
        records = db.query(Record).filter(
            Record.user_id == user_id, Record.date == d
        ).all()
        week_done += len(records)
    total = total_possible * 7
    return {
        "done": week_done,
        "total": total,
        "pct": round(week_done / total * 100) if total else 0,
    }


@app.get("/api/points")
def get_points(user_id: str, db: Session = Depends(get_db)):
    total_raw, bonus, redeemed, available = _calc_points(user_id, db)
    rewards = db.query(Reward).filter(
        Reward.user_id == user_id
    ).order_by(Reward.sort_order, Reward.threshold).all()
    weekly = _calc_weekly_stats(user_id, db)
    today = datetime.now()
    if bonus > 0:
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
        existing = db.query(Broadcast).filter(
            Broadcast.type == "auto",
            Broadcast.user_id == user_id,
            Broadcast.content.like("本周达标%"),
            Broadcast.created_at >= week_start,
        ).first()
        if not existing:
            db.add(Broadcast(
                user_id=user_id,
                type="auto",
                content="本周达标 🎉 +30 分",
            ))
            db.commit()
    return {
        "total_raw": total_raw,
        "bonus": bonus,
        "redeemed": redeemed,
        "available": available,
        "rewards": [
            {
                "id": r.id,
                "threshold": r.threshold,
                "label": r.label,
                "redeemed_count": r.redeemed_count,
                "sort_order": r.sort_order,
            }
            for r in rewards
        ],
        "weekly": {
            "week": today.isocalendar()[1],
            "done": weekly["done"],
            "total": weekly["total"],
            "pct": weekly["pct"],
            "qualifies": weekly["pct"] >= 70,
            "bonus_points": bonus,
            "claimed_this_week": bonus > 0,
        },
    }


@app.post("/api/rewards")
def create_reward(
    req: RewardCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    count = db.query(Reward).filter(Reward.user_id == CONFIG_USER_ID).count()
    for uid in ALL_USERS:
        db.add(Reward(
            user_id=uid,
            threshold=req.threshold,
            label=req.label,
            sort_order=count,
        ))
    db.commit()
    return {"status": "ok"}


@app.post("/api/rewards/claim")
def claim_reward(req: ClaimRequest, db: Session = Depends(get_db)):
    reward = db.query(Reward).filter(
        Reward.id == req.reward_id, Reward.user_id == req.user_id
    ).first()
    if not reward:
        raise HTTPException(404, "Reward not found")
    total_raw, bonus, redeemed, available = _calc_points(req.user_id, db)
    if available < reward.threshold:
        raise HTTPException(400, "Not enough points")
    reward.redeemed_count += 1
    db.add(Broadcast(
        user_id=req.user_id,
        type="auto",
        content=f"兑换了 {reward.label}",
    ))
    db.add(RedemptionLog(
        user_id=req.user_id,
        reward_id=reward.id,
        reward_label=reward.label,
        threshold=reward.threshold,
        redeemed_at=datetime.now(),
    ))
    db.commit()
    return {"status": "ok"}


@app.get("/api/rewards/history")
def get_redemption_history(user_id: str, db: Session = Depends(get_db)):
    logs = db.query(RedemptionLog).filter(
        RedemptionLog.user_id == user_id
    ).order_by(RedemptionLog.redeemed_at.desc()).limit(50).all()
    return [
        {
            "id": log.id,
            "reward_label": log.reward_label,
            "threshold": log.threshold,
            "redeemed_at": log.redeemed_at.isoformat(),
        }
        for log in logs
    ]


@app.put("/api/rewards/reorder")
def reorder_rewards(
    req: RewardReorderRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    if not req.rewards:
        raise HTTPException(400, "Rewards cannot be empty")

    ordered_items = sorted(req.rewards, key=lambda item: item.sort_order)
    source_rewards = []
    for item in ordered_items:
        reward = db.query(Reward).filter(Reward.id == item.id).first()
        if not reward:
            raise HTTPException(404, "Reward not found")
        source_rewards.append(reward)

    if len({reward.user_id for reward in source_rewards}) > 1:
        raise HTTPException(400, "Rewards must belong to the same user")

    ordered_configs = [
        {
            "threshold": reward.threshold,
            "label": reward.label,
            "old_sort_order": reward.sort_order,
            "sort_order": order,
        }
        for order, reward in enumerate(source_rewards)
    ]

    for order, reward in enumerate(source_rewards):
        reward.sort_order = order

    source_user_id = source_rewards[0].user_id if source_rewards else CONFIG_USER_ID
    for uid in ALL_USERS:
        if uid == source_user_id:
            continue
        redeemed_by_order = {
            reward.sort_order: reward.redeemed_count
            for reward in db.query(Reward).filter(Reward.user_id == uid).all()
        }
        db.query(Reward).filter(Reward.user_id == uid).delete()
        for config in ordered_configs:
            db.add(Reward(
                user_id=uid,
                threshold=config["threshold"],
                label=config["label"],
                redeemed_count=redeemed_by_order.get(config["old_sort_order"], 0),
                sort_order=config["sort_order"],
            ))

    db.commit()
    return {"status": "ok"}


@app.put("/api/rewards/{reward_id}")
def update_reward(
    reward_id: int,
    req: RewardCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(404, "Reward not found")
    reward_order = reward.sort_order
    rewards = db.query(Reward).filter(Reward.sort_order == reward_order).all()
    if any(r.redeemed_count > 0 for r in rewards):
        raise HTTPException(400, "Rewards that have been redeemed cannot be modified")
    for item in rewards:
        item.threshold = req.threshold
        item.label = req.label
    db.commit()
    return {"status": "ok"}


@app.delete("/api/rewards/{reward_id}")
def delete_reward(
    reward_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(404, "Reward not found")
    rewards = db.query(Reward).filter(Reward.sort_order == reward.sort_order).all()
    if any(r.redeemed_count > 0 for r in rewards):
        raise HTTPException(400, "Rewards that have been redeemed cannot be deleted")
    for item in rewards:
        db.delete(item)
    db.commit()
    return {"status": "ok"}


# ── Admin ──


@app.post("/api/admin/login")
def admin_login(req: AdminLogin):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(403, "Invalid password")
    return {"status": "ok", "token": _admin_token()}


@app.get("/api/admin/dashboard")
def get_admin_dashboard(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    users = db.query(User).all()
    all_habits = db.query(Habit).all()
    all_records = db.query(Record).all()
    all_rewards = db.query(Reward).all()

    users_data = {}
    for u in users:
        user_habits = [h for h in all_habits if h.user_id == u.id]
        user_records = [r for r in all_records if r.user_id == u.id]
        user_rewards = sorted(
            [r for r in all_rewards if r.user_id == u.id],
            key=lambda r: (r.sort_order, r.threshold),
        )

        total_raw, bonus, redeemed, available = _calc_points(u.id, db)
        record_dates = {}
        for r in user_records:
            if r.date not in record_dates:
                record_dates[r.date] = []
            record_dates[r.date].append(r.habit_key)

        habit_freq = {}
        for h in user_habits:
            count = len([r for r in user_records if r.habit_key == h.key])
            habit_freq[h.key] = {"label": h.label, "count": count, "points": h.points, "sort_order": h.sort_order}

        logs = db.query(RedemptionLog).filter(
            RedemptionLog.user_id == u.id
        ).order_by(RedemptionLog.redeemed_at.desc()).limit(20).all()

        adj_sum = db.query(
            func.coalesce(func.sum(PointAdjustment.amount), 0)
        ).filter(PointAdjustment.user_id == u.id).scalar()

        users_data[u.id] = {
            "id": u.id,
            "display_name": u.display_name,
            "emoji": u.emoji,
            "total_raw_points": total_raw,
            "bonus_points": bonus,
            "redeemed_points": redeemed,
            "points_adjustment": adj_sum,
            "available_points": available,
            "daily_records": record_dates,
            "habit_frequency": habit_freq,
            "rewards": [
                {
                    "id": r.id,
                    "label": r.label,
                    "threshold": r.threshold,
                    "redeemed_count": r.redeemed_count,
                    "sort_order": r.sort_order,
                }
                for r in user_rewards
            ],
            "redemption_logs": [
                {
                    "reward_label": log.reward_label,
                    "threshold": log.threshold,
                    "redeemed_at": log.redeemed_at.isoformat(),
                }
                for log in logs
            ],
        }

    return list(users_data.values())


@app.post("/api/admin/adjust-points")
def admin_adjust_points(
    req: AdjustPointsRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.add(PointAdjustment(
        user_id=req.user_id,
        amount=req.amount,
        reason=req.reason,
    ))
    db.commit()
    logger.info(f"Adjusted points for {req.user_id}: {req.amount:+d} ({req.reason})")
    return {"status": "ok"}


# ── Broadcasts (shared feed) ──


@app.get("/api/broadcasts")
def get_broadcasts(limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    broadcasts = db.query(Broadcast).order_by(
        Broadcast.created_at.desc()
    ).limit(limit).all()
    user_cache = {u.id: u for u in db.query(User).all()}
    return [
        {
            "id": b.id,
            "user_id": b.user_id,
            "user_display_name": user_cache[b.user_id].display_name,
            "user_emoji": user_cache[b.user_id].emoji,
            "type": b.type,
            "content": b.content,
            "created_at": b.created_at.isoformat(),
        }
        for b in broadcasts
    ]


@app.post("/api/broadcasts")
def create_broadcast(req: BroadcastRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.add(Broadcast(
        user_id=req.user_id,
        type="manual",
        content=req.content,
    ))
    db.commit()
    return {"status": "ok"}


# ── Reset All Data ──

@app.post("/api/reset-all")
def reset_all_data(db: Session = Depends(get_db)):
    """Reset all operational data for both users: records, redemptions,
    point adjustments, broadcasts, and reward redemption counts."""
    import sqlalchemy
    db.execute(sqlalchemy.text("DELETE FROM records"))
    db.execute(sqlalchemy.text("DELETE FROM redemption_logs"))
    db.execute(sqlalchemy.text("DELETE FROM point_adjustments"))
    db.execute(sqlalchemy.text("DELETE FROM broadcasts"))
    db.execute(sqlalchemy.text("UPDATE rewards SET redeemed_count = 0"))
    db.commit()
    logger.info("All data reset complete")
    return {"status": "ok"}


# ── Static files ──

app.mount("/", StaticFiles(directory="static", html=True), name="static")
