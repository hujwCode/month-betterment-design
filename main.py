from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import date, datetime, timedelta
import calendar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from database import init_db, get_db, SessionLocal
from models import User, Habit, Record, Reward

app = FastAPI(title="一个月变好")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    for uid, name, emoji in [("me", "我", "🙋"), ("wife", "女王大人", "👑")]:
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
    for uid, _, _ in [("me", "我", "🙋"), ("wife", "女王大人", "👑")]:
        for key, label, pts, order in default_habits:
            if not db.query(Habit).filter(Habit.user_id == uid, Habit.key == key).first():
                db.add(Habit(user_id=uid, key=key, label=label, points=pts, sort_order=order))
    default_rewards = [
        (100, "🍦 一起吃个冰淇淋", 0),
        (200, "🎲 一起玩桌游/游戏之夜", 1),
        (400, "🍽️ 去一家想去的餐厅", 2),
        (700, "🏕️ 周末短途旅行", 3),
    ]
    for uid, _, _ in [("me", "我", "🙋"), ("wife", "女王大人", "👑")]:
        for thresh, label, order in default_rewards:
            if not db.query(Reward).filter(Reward.user_id == uid, Reward.threshold == thresh).first():
                db.add(Reward(user_id=uid, threshold=thresh, label=label, sort_order=order))
    db.commit()
    db.close()


# ── Pydantic models ──

class LoginRequest(BaseModel):
    user_id: str

class HabitCreate(BaseModel):
    user_id: str
    key: str
    label: str
    points: int
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

class AdminLogin(BaseModel):
    password: str

class ReorderItem(BaseModel):
    key: str
    sort_order: int

class ReorderRequest(BaseModel):
    habits: list[ReorderItem]


# ── User / Habits ──

@app.post("/api/login")
def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    habits = db.query(Habit).filter(Habit.user_id == req.user_id).order_by(Habit.sort_order).all()
    rewards = db.query(Reward).filter(Reward.user_id == req.user_id).order_by(Reward.sort_order).all()
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
            {"id": r.id, "threshold": r.threshold, "label": r.label, "claimed": r.claimed}
            for r in rewards
        ],
        "today_records": {r.habit_key: True for r in today_records},
    }


ALL_USERS = ["me", "wife"]

@app.get("/api/habits")
def get_habits(user_id: str, db: Session = Depends(get_db)):
    habits = db.query(Habit).filter(Habit.user_id == user_id).order_by(Habit.sort_order).all()
    return [
        {"key": h.key, "label": h.label, "points": h.points, "sort_order": h.sort_order}
        for h in habits
    ]


@app.post("/api/habits")
def create_habit(req: HabitCreate, db: Session = Depends(get_db)):
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
def delete_habit(key: str, db: Session = Depends(get_db)):
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
def reorder_habits(req: ReorderRequest, db: Session = Depends(get_db)):
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
        db.commit()
        logger.info(f"Toggle {req.user_id}/{req.habit_key}: {msg}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Toggle failed: {e}")
        db.rollback()
        raise HTTPException(500, str(e))


@app.get("/api/records/month")
def get_month_records(user_id: str, year: int, month: int, db: Session = Depends(get_db)):
    month_str = f"{year}-{month:02d}"
    records = db.query(Record).filter(
        Record.user_id == user_id, Record.date.like(f"{month_str}%")
    ).all()
    days_in_month = calendar.monthrange(year, month)[1]
    habits = {h.key: h.points for h in db.query(Habit).filter(Habit.user_id == user_id).all()}

    result = {}
    for d in range(1, days_in_month + 1):
        date_str = f"{month_str}-{d:02d}"
        day_list = [(r.habit_key, True) for r in records if r.date == date_str]
        day_records = dict(day_list)
        day_points = sum(habits.get(k, 0) for k in day_records)
        result[date_str] = {
            "done_count": len(day_records),
            "points": day_points,
            "habits": day_records,
        }
    return result


@app.get("/api/week-stats")
def get_week_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.now()
    weekday = today.weekday()
    week_start = datetime(today.year, today.month, today.day - weekday)
    habit_keys = [
        h.key for h in db.query(Habit).filter(Habit.user_id == user_id).all()
    ]
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


# ── Points & Rewards ──

def _calc_points(user_id: str, db: Session):
    records = db.query(Record).filter(Record.user_id == user_id).all()
    habits = {
        h.key: h.points
        for h in db.query(Habit).filter(Habit.user_id == user_id).all()
    }
    total_raw = sum(habits.get(r.habit_key, 0) for r in records)
    rewards = db.query(Reward).filter(Reward.user_id == user_id).all()
    redeemed = sum(r.threshold for r in rewards if r.claimed)
    return total_raw, redeemed, total_raw - redeemed


@app.get("/api/points")
def get_points(user_id: str, db: Session = Depends(get_db)):
    total_raw, redeemed, available = _calc_points(user_id, db)
    rewards = db.query(Reward).filter(Reward.user_id == user_id).order_by(Reward.sort_order).all()
    return {
        "total_raw": total_raw,
        "redeemed": redeemed,
        "available": available,
        "rewards": [
            {"id": r.id, "threshold": r.threshold, "label": r.label, "claimed": r.claimed}
            for r in rewards
        ],
    }


@app.post("/api/rewards")
def create_reward(req: RewardCreate, db: Session = Depends(get_db)):
    count = db.query(Reward).filter(Reward.user_id == req.user_id).count()
    db.add(Reward(
        user_id=req.user_id, threshold=req.threshold,
        label=req.label, sort_order=count,
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
    if reward.claimed:
        raise HTTPException(400, "Already claimed")
    total_raw, redeemed, _ = _calc_points(req.user_id, db)
    if total_raw - redeemed < reward.threshold:
        raise HTTPException(400, "Not enough points")
    reward.claimed = True
    db.commit()
    return {"status": "ok"}


@app.delete("/api/rewards/{reward_id}")
def delete_reward(reward_id: int, db: Session = Depends(get_db)):
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(404, "Reward not found")
    db.delete(reward)
    db.commit()
    return {"status": "ok"}


# ── Admin ──

ADMIN_PASSWORD = "admin123"


@app.post("/api/admin/login")
def admin_login(req: AdminLogin):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(403, "Invalid password")
    return {"status": "ok"}


@app.get("/api/admin/dashboard")
def get_admin_dashboard(db: Session = Depends(get_db)):
    users = db.query(User).all()
    all_habits = db.query(Habit).all()
    all_records = db.query(Record).all()
    all_rewards = db.query(Reward).all()

    users_data = {}
    for u in users:
        user_habits = [h for h in all_habits if h.user_id == u.id]
        user_records = [r for r in all_records if r.user_id == u.id]
        user_rewards = [r for r in all_rewards if r.user_id == u.id]

        total_raw = 0
        record_dates = {}
        for r in user_records:
            h = next((h for h in user_habits if h.key == r.habit_key), None)
            if h:
                total_raw += h.points
            if r.date not in record_dates:
                record_dates[r.date] = []
            record_dates[r.date].append(r.habit_key)

        habit_freq = {}
        for h in user_habits:
            count = len([r for r in user_records if r.habit_key == h.key])
            habit_freq[h.key] = {"label": h.label, "count": count, "points": h.points}

        users_data[u.id] = {
            "id": u.id,
            "display_name": u.display_name,
            "emoji": u.emoji,
            "total_raw_points": total_raw,
            "daily_records": record_dates,
            "habit_frequency": habit_freq,
            "rewards": [
                {"id": r.id, "label": r.label, "threshold": r.threshold, "claimed": r.claimed}
                for r in user_rewards
            ],
        }

    return list(users_data.values())


# ── Static files ──

app.mount("/", StaticFiles(directory="static", html=True), name="static")
