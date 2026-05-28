# ✨ 小进步

> 和他/她一起，每天小进步一点点。

两个用户、七个习惯、一张积分表。不是又一个打卡 App——是两个人互相看着对方进步的小工具。

每天打勾做完的习惯会变成积分，积分够了就兑换一个奖励。一杯想喝的饮品、一次 SPA、一顿计划了很久的晚餐——把期待变成动力。

## 亮点

- **双人模式** — 你和另一半各自打卡，同一个奖励池，互相激励
- **积分 = 动力** — 每个习惯有分值，攒够了就兑奖，形成正向循环
- **周奖励机制** — 每周完成率超过 70%，额外奖励 30 分
- **管理后台** — 习惯管理、奖励编辑、热力图和完成率趋势一目了然
- **极简部署** — 一个 Python 文件 + SQLite，单机可跑，零外部依赖

## 技术栈

| 层 | 技术 |
|------|------|
| 后端 | Python 3.9+ / FastAPI |
| 数据库 | SQLite / SQLAlchemy |
| 前端 | Vanilla JS SPA（无框架） |
| 部署 | systemd + Nginx + uvicorn |

## 部署

### 服务器要求

- Ubuntu 20.04+
- Python 3.9+
- Nginx

### 一键部署

登录服务器，以 root 或 ubuntu 用户运行：

```bash
bash <(curl -sL https://raw.githubusercontent.com/hujwCode/month-betterment-design/main/deploy.sh)
```

部署脚本会自动完成：安装依赖 → 拉取代码 → 配置 Python 环境 → 创建 systemd 服务 → 配置 Nginx 反向代理 → 启动服务。

部署完成后访问 `http://<你的服务器IP>` 即可使用。

### 手动部署

```bash
# 1. 安装依赖
sudo apt install -y python3-pip python3-venv nginx

# 2. 拉取代码
git clone https://github.com/hujwCode/month-betterment-design.git /var/www/month-betterment-server

# 3. 配置 Python 环境
cd /var/www/month-betterment-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 创建 systemd 服务
sudo tee /etc/systemd/system/month-betterment.service << 'EOF'
[Unit]
Description=Month Betterment FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/month-betterment-server
ExecStart=/var/www/month-betterment-server/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable month-betterment
sudo systemctl start month-betterment

# 5. 配置 Nginx 反向代理
sudo tee /etc/nginx/sites-available/month-betterment << 'EOF'
server {
    listen 80;
    server_name your-server-ip;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/month-betterment /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

### 更新

服务端运行：

```bash
bash /var/www/month-betterment-server/update.sh
```

### 本地开发

```bash
git clone https://github.com/hujwCode/month-betterment-design.git
cd month-betterment-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

打开 `http://localhost:8080` 即可。

## 默认数据

**用户**：🙋 我 / 👑 女王大人

**习惯**（7 项，每项有对应分值）：
| 习惯 | 分值 |
|------|------|
| 📖 阅读 30 分钟 | 20 分 |
| 💧 喝水 1.5L | 10 分 |
| 🏃 运动 20 分钟 | 15 分 |
| 📱 22:30 前放下手机 | 10 分 |
| 🍬 控糖 | 10 分 |
| 👶 陪宝宝 30-60 分钟 | 15 分 |
| 🍽️ 吃饭不玩手机 | 5 分 |

**奖励阶梯**：50 分 → 1500 分，从一杯饮品到周末短途旅行。

**管理后台**：`/admin.html`，默认密码 `admin123`。

## 项目结构

```
month-betterment-server/
├── main.py              # FastAPI 应用（路由 + 业务逻辑）
├── models.py            # SQLAlchemy 数据模型
├── database.py          # 数据库连接配置
├── requirements.txt     # Python 依赖
├── deploy.sh            # 服务器一键部署脚本
├── update.sh            # 服务器更新脚本
├── static/
│   ├── index.html       # 用户前端（打卡 + 积分 + 奖励）
│   ├── admin.html       # 管理后台（看板 + 配置）
│   └── versions.json    # 更新日志数据
└── month-betterment.db  # SQLite 数据库（自动创建）
```
