# 📢 小喇叭功能 · 设计文档

## 概述

为双人打卡应用"一个月变好"增加小喇叭（Broadcast）功能，包含自动动态播报和手动喊话两种内容类型，并集成到打卡页顶部轮播条和独立动态 Tab 中。

## 数据模型

### Broadcast 表

```python
class Broadcast(Base):
    __tablename__ = "broadcasts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)       # "auto" 或 "manual"
    content = Column(String, nullable=False)     # 播报文本（服务端渲染好中文）
    created_at = Column(DateTime, default=datetime.now)
```

```sql
CREATE TABLE broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    type TEXT NOT NULL CHECK(type IN ('auto','manual')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_broadcasts_user_created ON broadcasts(user_id, created_at DESC);
```

### 自动播报内容生成规则

| 触发事件 | 位置 | content 格式示例 |
|---------|------|----------------|
| 完成打卡 | `toggle_habit` 新增记录时 | `完成了 💧 喝水 1.5L` |
| 兑换奖励 | `claim_reward` 成功后 | `兑换了 🍵 一杯想喝的饮品` |
| 周奖励达标 | `_calc_points` 中首次达标时 | `本周达标 🎉 +30 分` |

每条 content 在服务端渲染成完整中文文本，不包含用户标识（用户标识在 API 返回时附带）。

取消打卡、删除奖励等操作不产生播报，避免信息噪音。

## API 设计

### 获取动态列表

```
GET /api/broadcasts?user_id=me&limit=50
```

Response:

```json
[
  {
    "id": 1,
    "user_id": "wife",
    "user_display_name": "女王大人",
    "user_emoji": "👑",
    "type": "auto",
    "content": "完成了 💧 喝水 1.5L",
    "created_at": "2026-05-28T09:41:00"
  }
]
```

按 `created_at DESC` 排序，limit 默认 50。

### 手动喊话

```
POST /api/broadcasts
Body: { "user_id": "me", "content": "今天辛苦啦 🥰" }
Response: { "status": "ok" }
```

限制 content 长度不超过 200 字符。

### 新增自动播报

不单独提供 API，在现有业务逻辑中嵌入写入逻辑：

- `toggle_habit`：当操作是"新增打卡记录"（非取消）时，写入一条 `type=auto` 的 broadcast
- `claim_reward`：兑换成功后，写入一条 `type=auto` 的 broadcast
- 周奖励：在 `_calc_points` 中检测首次达标时写入

## 前端设计

### 打卡页顶部轮播条

位于积分卡上方，紧贴导航栏下方：

```
┌──────────────────────────────┐
│ [打卡] [数据] [兑换] [📢] [设置]│
├──────────────────────────────┤
│ 📢 👑 完成了 💧 喝水 1.5L  │  ← 绿色渐变背景
│                     ●○○ 更多›│  ← 2秒自动切换
├──────────────────────────────┤
│        可用积分              │
│          35                  │
├──────────────────────────────┤
│ ✅ 💧 喝水 1.5L       +10   │
│ ·  🏃 运动 20分钟    +15   │
└──────────────────────────────┘
```

**视觉规格**：
- 背景：绿色渐变 `linear-gradient(135deg, #8B9D83, #A8C9A5)`
- 喇叭图标：白色半透明圆角方块，白字
- 文本颜色：白色
- 时间标签：白色半透明
- 小圆点：当前白色实心，其余白色半透明
- 高度：约 44px（含 padding）
- 底部：用 1px 分割线与内容区隔

**交互行为**：
- 自动垂直轮播，每次显示一条，2 秒切换到下一条
- 切换动画：旧消息向上滑出 + 新消息滑入，300ms ease
- 最多轮播最近 20 条
- 点击任意一条 → 切换到 📢 动态 Tab
- 点击「更多」→ 切换到 📢 动态 Tab
- 触摸/悬停时暂停轮播
- 仅打卡页显示，其他 Tab 隐藏

**前端实现要点**：
- 使用 CSS `overflow: hidden` 固定高度容器 + `transform: translateY` 动画实现垂直轮播
- `setInterval` 控制切换节奏，2 秒
- `touchstart` / `mouseenter` 时 `clearInterval`，`touchend` / `mouseleave` 时重启
- 页面隐藏（`visibilitychange`）时暂停轮播

### 📢 动态独立 Tab

完整的动态列表页：

```
┌──────────────────────────────┐
│ [打卡] [数据] [兑换] [📢] [设置]│
├──────────────────────────────┤
│ 🙋 [________________] [发送] │  ← 手动喊话输入框
├──────────────────────────────┤
│ 👑 完成了 💧 喝水 1.5L     │
│                      🔔 刚刚│
├──────────────────────────────┤
│ 🙋 今天辛苦啦 🥰           │
│                      💬 5分钟│
├──────────────────────────────┤
│ 👑 兑换了 🍵 一杯饮品      │
│                      🔔 30分│
└──────────────────────────────┘
```

**交互行为**：
- 加载最近 50 条动态
- 自动播报显示 🔔 图标，手动喊话显示 💬 图标
- 每条显示：用户 emoji、用户名、内容、时间
- 时间显示：X分钟前、X小时前、X天前

## 触发逻辑细节

### 打卡触发

在 `toggle_habit` 中，仅在"新增记录"（`msg == "created"`）时写入 broadcast：

```python
if msg == "created":
    habit = db.query(Habit).filter(
        Habit.user_id == req.user_id, Habit.key == req.habit_key
    ).first()
    if habit:
        db.add(Broadcast(
            user_id=req.user_id,
            type="auto",
            content=f"完成了 {habit.label}",
        ))
```

### 兑换触发

在 `claim_reward` 中 `reward.redeemed_count += 1` 之后：

```python
db.add(Broadcast(
    user_id=req.user_id,
    type="auto",
    content=f"兑换了 {reward.label}",
))
```

### 周奖励触发

在 `get_points` 接口中检测：`bonus > 0` 且本周尚未产生周奖励播报时写入一条。

```python
if bonus > 0:
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    existing = db.query(Broadcast).filter(
        Broadcast.user_id == user_id,
        Broadcast.type == "auto",
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
```

`get_points` 每次被调用都会检测，但因为有了去重检查（同一周只写一条），不会重复写入。

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `models.py` | 新增 `Broadcast` 模型 |
| `main.py` | 新增 API 路由、自动播报嵌入逻辑、导入 Broadcast 和 migration |
| `static/index.html` | 新增打卡页顶部轮播条、新增 📢 动态 Tab 及其内容渲染 |

## 未涉及 / 后续可扩展

- 删除动态（当前不做，数据量小，SQLite 无压力）
- 动态红点提示（当前不做，后续可加）
- 消息推送（网页端无法主动推送）
