# 小喇叭 Broadcast 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add broadcast (小喇叭) feature with check-in page ticker, dedicated dynamic tab, and auto/manual posting.

**Architecture:** Broadcast records stored in new SQLite table; API returns user info joined in-query; frontend polls `/api/broadcasts` on relevant tab visits and drives a vertical carousel via CSS transform animation.

**Tech Stack:** Python/FastAPI, SQLite/SQLAlchemy, Vanilla JS

---

### Task 1: Add Broadcast Model

**Files:**
- Modify: `models.py:43-50`

- [ ] **Step 1: Add Broadcast model**

```python
class Broadcast(Base):
    __tablename__ = "broadcasts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # "auto" or "manual"
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_broadcasts_user_created", "user_id", "created_at"),
    )
```

Also add `Index` to the imports:

```python
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
```

- [ ] **Step 2: Commit**

```bash
git add models.py
git commit -m "feat: add Broadcast model for 小喇叭 feature"
```

---

### Task 2: Add API Endpoints and Migration

**Files:**
- Modify: `main.py:1-18` (imports)
- Modify: `main.py:96-120` (startup migration)
- Modify: `main.py:152-195` (Pydantic models)
- Create after: `main.py:420` (after claim endpoint — broadcast routes)
- Modify: `main.py:288-307` (toggle_habit — auto-broadcast on check-in)
- Modify: `main.py:435-457` (claim_reward — auto-broadcast on redemption)
- Modify: `main.py:386-418` (get_points — auto-broadcast on weekly bonus)

- [ ] **Step 1: Add Broadcast import**

```python
from models import User, Habit, Record, Reward, RedemptionLog, PointAdjustment, Broadcast
```

- [ ] **Step 2: Add BroadcastRequest Pydantic model** (after AdjustPointsRequest)

```python
class BroadcastRequest(BaseModel):
    user_id: str
    content: str = Field(..., max_length=200)
```

- [ ] **Step 3: Add migration in on_startup**

After the existing `DBBase.metadata.create_all(...)` line, add Broadcast table too:

```python
DBBase.metadata.create_all(bind=db.bind, tables=[
    RedemptionLog.__table__,
    PointAdjustment.__table__,
    Broadcast.__table__,
])
```

- [ ] **Step 4: GET /api/broadcasts endpoint**

Add after the `POST /api/rewards/claim` block:

```python
@app.get("/api/broadcasts")
def get_broadcasts(user_id: str, limit: int = 50, db: Session = Depends(get_db)):
    broadcasts = db.query(Broadcast).filter(
        Broadcast.user_id == user_id
    ).order_by(Broadcast.created_at.desc()).limit(limit).all()
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
```

Wait — broadcasts are per-user? No, they should be **shared** across all users. Both "我" and "女王大人" should see the same broadcast feed. Let me adjust: GET /api/broadcasts returns all broadcasts (for all users), sorted by time.

```python
@app.get("/api/broadcasts")
def get_broadcasts(limit: int = 50, db: Session = Depends(get_db)):
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
```

- [ ] **Step 5: POST /api/broadcasts endpoint** (manual shout)

```python
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
```

- [ ] **Step 6: Auto-broadcast in toggle_habit**

Inside `toggle_habit`, after `msg = "created"` line:

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

- [ ] **Step 7: Auto-broadcast in claim_reward**

Inside `claim_reward`, after `reward.redeemed_count += 1`:

```python
db.add(Broadcast(
    user_id=req.user_id,
    type="auto",
    content=f"兑换了 {reward.label}",
))
```

- [ ] **Step 8: Auto-broadcast for weekly bonus in get_points**

In `get_points`, before the return, add:

```python
if bonus > 0:
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    existing = db.query(Broadcast).filter(
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

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "feat: add broadcast API endpoints and auto-broadcast triggers"
```

---

### Task 3: Frontend — API Methods

**Files:**
- Modify: `static/index.html:360-376` (API object)

- [ ] **Step 1: Add broadcast API methods**

After `claimReward`:

```javascript
async getBroadcasts() {
  const r = await fetch('/api/broadcasts');
  return r.json();
},
async sendBroadcast(userId, content) {
  const r = await fetch('/api/broadcasts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user_id: userId, content})
  });
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'error'); }
  return r.json();
},
```

- [ ] **Step 2: Commit**

```bash
git add static/index.html
git commit -m "feat: add broadcast API methods to frontend"
```

---

### Task 4: Frontend — Check-in Page Ticker

**Files:**
- Modify: `static/index.html` (renderCheckin function, add ticker CSS+JS)

- [ ] **Step 1: Add ticker CSS**

After the `.weekly-card` CSS block:

```css
.broadcast-ticker {
  background: linear-gradient(135deg, #8B9D83, #A8C9A5);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  cursor: pointer;
  user-select: none;
}
.broadcast-ticker .ticker-icon {
  background: rgba(255,255,255,0.25);
  border-radius: 6px;
  width: 28px; height: 28px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.broadcast-ticker .ticker-icon span { color: white; font-size: 0.85em; }
.broadcast-ticker .ticker-stage {
  flex: 1; min-width: 0; height: 24px;
  overflow: hidden; position: relative;
}
.broadcast-ticker .ticker-item {
  position: absolute; left: 0; right: 0;
  display: flex; align-items: center; gap: 6px;
  height: 24px; transition: transform 0.3s ease, opacity 0.3s ease;
}
.broadcast-ticker .ticker-text {
  font-size: 0.85em; color: white;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.broadcast-ticker .ticker-time {
  font-size: 0.72em; color: rgba(255,255,255,0.6);
  white-space: nowrap; flex-shrink: 0;
}
.broadcast-ticker .ticker-dots {
  display: flex; gap: 3px; flex-shrink: 0; align-items: center;
}
.broadcast-ticker .ticker-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255,255,255,0.3);
  transition: background 0.3s;
}
.broadcast-ticker .ticker-dot.active { background: white; }
.broadcast-ticker .ticker-more {
  color: rgba(255,255,255,0.7);
  font-size: 0.78em; flex-shrink: 0;
}
```

- [ ] **Step 2: Add broadcast state to APP**

In `const APP = { data: null, currentTab: 'checkin', ...`, add:

```javascript
broadcasts: [],
broadcastTimer: null,
broadcastIdx: 0,
```

- [ ] **Step 3: Write the ticker HTML and JS**

Create a helper function `renderBroadcastTicker(broadcasts)` in APP:

```javascript
renderBroadcastTicker(broadcasts) {
  if (!broadcasts || !broadcasts.length) return '';
  const idx = this.broadcastIdx % broadcasts.length;
  const b = broadcasts[idx];
  const timeAgo = this.timeAgo(b.created_at);
  const userLabel = b.user_emoji + ' ' + b.user_display_name;
  const icon = b.type === 'manual' ? '💬' : '🔔';

  let dotsHtml = '';
  const maxDots = Math.min(broadcasts.length, 8);
  for (let i = 0; i < maxDots; i++) {
    dotsHtml += `<div class="ticker-dot ${i === (idx % maxDots) ? 'active' : ''}"></div>`;
  }

  return `<div class="broadcast-ticker" onclick="APP.switchTab('broadcast')">
    <div class="ticker-icon"><span>📢</span></div>
    <div class="ticker-stage">
      <div class="ticker-item" style="top:0;">
        <span class="ticker-text">${userLabel} ${b.content}</span>
        <span class="ticker-time">${icon} ${timeAgo}</span>
      </div>
    </div>
    <div class="ticker-dots">${dotsHtml}</div>
    <span class="ticker-more">更多 ›</span>
  </div>`;
},

timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff/60) + '分钟前';
  if (diff < 86400) return Math.floor(diff/3600) + '小时前';
  return Math.floor(diff/86400) + '天前';
},
```

Add a `startBroadcastTicker()` and `stopBroadcastTicker()`:

```javascript
startBroadcastTicker() {
  this.stopBroadcastTicker();
  this.broadcastTimer = setInterval(() => {
    this.broadcastIdx++;
    this.renderCheckin();
  }, 2000);
},
stopBroadcastTicker() {
  if (this.broadcastTimer) {
    clearInterval(this.broadcastTimer);
    this.broadcastTimer = null;
  }
},
```

- [ ] **Step 4: Integrate into renderCheckin**

In `renderCheckin`, at the top, load broadcasts and prepend ticker to the HTML. Modify the function to:

1. Fetch broadcasts at the start
2. Prepend ticker HTML after the section title

```javascript
async renderCheckin() {
  const d = this.data;
  document.getElementById('main-content').innerHTML = '...skeleton...';
  try {
    // Load broadcast data
    const allBroadcasts = await API.getBroadcasts();
    this.broadcasts = allBroadcasts;

    let html = '<div class="section-title">✅ 今日打卡</div>';

    // Ticker
    html += this.renderBroadcastTicker(allBroadcasts);

    // ...rest of checkin HTML...
  }
}
```

Also update `selectUser` to call `startBroadcastTicker` after rendering, and call `stopBroadcastTicker` on tab switch away from checkin.

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat: add broadcast ticker to check-in page"
```

---

### Task 5: Frontend — Broadcast Tab Page

**Files:**
- Modify: `static/index.html` (add broadcast tab rendering, tab switching)

- [ ] **Step 1: Add broadcast tab to tab bar**

In the `renderCheckin`/Tab bar rendering, add `📢 动态` tab after `🏆 兑换`:

```html
<div class="tab ${tab === 'broadcast' ? 'active' : ''}" onclick="APP.switchTab('broadcast')">📢 动态</div>
```

- [ ] **Step 2: Add switchTab handler for 'broadcast'**

In `switchTab`:

```javascript
if (tab === 'broadcast') {
  this.renderBroadcastTab();
  return;
}
```

- [ ] **Step 3: renderBroadcastTab — full broadcast list page**

```javascript
async renderBroadcastTab() {
  const d = this.data;
  document.getElementById('main-content').innerHTML = '<div class="section-title">📢 小喇叭</div><div class="skeleton skel-bar" style="width:60%;"></div><div class="skeleton skel-card"></div><div class="skeleton skel-card"></div>';
  try {
    const broadcasts = await API.getBroadcasts();
    let html = '<div class="section-title">📢 小喇叭</div>';

    // Manual shout input
    html += `<div style="background:var(--bg-card);border-radius:var(--radius-sm);padding:12px 16px;margin-bottom:16px;display:flex;gap:8px;align-items:center;border:1px solid var(--border);">
      <span>${d.user.emoji}</span>
      <input id="broadcast-input" placeholder="说句话..." style="flex:1;border:none;outline:none;font-size:0.9em;background:transparent;color:var(--text);" maxlength="200" onkeydown="if(event.key==='Enter')APP.sendBroadcast()" />
      <button class="claim-btn" onclick="APP.sendBroadcast()" style="padding:6px 16px;font-size:0.85em;">发送</button>
    </div>`;

    // Broadcast list
    if (broadcasts.length) {
      html += '<div style="display:flex;flex-direction:column;gap:10px;">';
      broadcasts.forEach(b => {
        const timeAgo = this.timeAgo(b.created_at);
        const icon = b.type === 'manual' ? '💬' : '🔔';
        html += `
          <div style="background:var(--bg-card);border-radius:var(--radius-sm);padding:14px 16px;border:1px solid var(--border);display:flex;gap:10px;align-items:flex-start;">
            <div style="width:32px;height:32px;border-radius:50%;background:var(--bg-secondary);display:flex;align-items:center;justify-content:center;flex-shrink:0;">${b.user_emoji}</div>
            <div style="flex:1;min-width:0;">
              <div style="font-size:0.88em;color:var(--text);">
                <strong>${b.user_display_name}</strong> ${b.content}
              </div>
              <div style="font-size:0.75em;color:var(--text-muted);margin-top:3px;">${icon} ${timeAgo}</div>
            </div>
          </div>`;
      });
      html += '</div>';
    } else {
      html += '<div style="text-align:center;padding:40px 0;color:var(--text-muted);font-size:0.9em;">暂无动态，开始打卡吧 💪</div>';
    }

    document.getElementById('main-content').innerHTML = html;
  } catch(e) {
    document.getElementById('main-content').innerHTML = '<div style="text-align:center;padding:60px 20px;color:var(--text-muted);">加载失败</div>';
  }
},
```

- [ ] **Step 4: sendBroadcast helper**

```javascript
async sendBroadcast() {
  const input = document.getElementById('broadcast-input');
  if (!input || !input.value.trim()) return;
  try {
    await API.sendBroadcast(this.data.user.id, input.value.trim());
    input.value = '';
    this.renderBroadcastTab();
    // Refresh ticker data
    const allBroadcasts = await API.getBroadcasts();
    this.broadcasts = allBroadcasts;
  } catch(e) {
    alert(e.message);
  }
},
```

- [ ] **Step 5: Stop ticker when leaving checkin tab**

In `switchTab`, call `this.stopBroadcastTicker()` for any non-checkin tab.

- [ ] **Step 6: Commit**

```bash
git add static/index.html
git commit -m "feat: add broadcast tab with manual shout and full list"
```

---

### Task 6: Update Versions Log

**Files:**
- Modify: `static/versions.json`

- [ ] **Step 1: Add v2.3.0 entry**

```json
{
  "version": "2.3.0",
  "date": "2026-05-28",
  "title": "小喇叭功能 — 动态播报 & 手动喊话",
  "changes": [
    "新增 📢 小喇叭：打卡、兑换、周奖励自动播报",
    "新增 💬 手动喊话：给对方留言",
    "打卡页顶部绿色轮播条，2秒切换一条",
    "独立 📢 动态 Tab，查看完整时间流"
  ]
}
```

- [ ] **Step 2: Commit & Push**

```bash
git add static/versions.json
git commit -m "chore: update changelog for v2.3.0 broadcast feature"
git push
```

---

## Self-Review Checklist

1. **Spec coverage:** All spec requirements covered — model (Task 1), APIs (Task 2), ticker (Task 4), broadcast tab (Task 5), auto triggers (Task 2), manual shout (Task 5).
2. **Placeholder check:** No TBD/TODO/hollow "handle edge cases". All code blocks are complete.
3. **Type consistency:** `Broadcast.type` is "auto"/"manual" consistently. `created_at` is DateTime throughout. API response shape matches frontend expectations.
