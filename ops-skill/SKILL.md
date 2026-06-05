---
name: little-progress-ops
description: "运维 Little Progress 服务器：查看状态、部署更新、配置 SSL、管理访问码。用于日常运维排查与部署。触发词：服务器状态、部署、重启、日志、SSL、nginx、systemd"
---

# Little Progress 服务器运维

> 基于 Ubuntu 24.04 + Nginx + systemd + uvicorn 的 FastAPI 应用运维指南。

## 快速命令速查

```bash
# SSH 登录（本地配好密钥后）
ssh little-progress-root

# 或直接 ssh root@43.153.155.195
```

### 服务管理

```bash
# 查看服务状态
systemctl status little-progress

# 启动 / 停止 / 重启
systemctl start little-progress
systemctl stop little-progress
systemctl restart little-progress

# 查看实时日志
journalctl -u little-progress -f -n 50

# 查看最近日志（不持续跟踪）
journalctl -u little-progress --no-pager -n 100
```

### 部署更新

```bash
cd /var/www/little-progress-server
git pull origin main
systemctl restart little-progress
```

或使用 update.sh：

```bash
bash /var/www/little-progress-server/update.sh
```

## 服务架构

```
客户端 → Nginx (80/443) → proxy_pass → uvicorn (127.0.0.1:8000) → FastAPI → SQLite
```

| 层 | 技术 | 端口 |
|----|------|------|
| 反向代理 | Nginx 1.24 | 80 (HTTP) / 443 (HTTPS) |
| Web 服务 | uvicorn + FastAPI | 127.0.0.1:8000 |
| 数据库 | SQLite | 文件：`/var/www/little-progress-server/little-progress.db` |

## Nginx 配置

位置：`/etc/nginx/sites-available/little-progress`

```nginx
server {
    listen 80;
    server_name little-progress.cloud www.little-progress.cloud 43.153.155.195;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name little-progress.cloud www.little-progress.cloud;

    ssl_certificate /etc/letsencrypt/live/little-progress.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/little-progress.cloud/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

修改后生效：

```bash
nginx -t && systemctl reload nginx
```

## SSL 证书

使用 Let's Encrypt（Certbot），证书存储在 `/etc/letsencrypt/live/little-progress.cloud/`。

```bash
# 查看证书状态
certbot certificates

# 手动续期（自动续期已配置 systemd timer，一般不需要手动）
certbot renew

# 申请新证书
certbot certonly --nginx -d little-progress.cloud -d www.little-progress.cloud
```

自动续期配置：certbot 的 systemd timer 每天检查，到期前 30 天自动续签。

## systemd 服务配置

位置：`/etc/systemd/system/little-progress.service`

```ini
[Unit]
Description=Little Progress FastAPI
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/little-progress-server
ExecStart=/var/www/little-progress-server/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MB_ADMIN_PASSWORD` | `admin123` | 管理后台登录密码 |
| `MB_ACCESS_CODE` | `xiaojinbu2025` | 前端访问码（用户打开页面时输入） |

设置环境变量需更新 systemd service 文件，在 `[Service]` 段添加：

```ini
Environment=MB_ACCESS_CODE=your_new_code
```

然后 `systemctl daemon-reload && systemctl restart little-progress`。

## 数据库

SQLite 文件位置：`/var/www/little-progress-server/little-progress.db`

```bash
# 备份数据库
cp /var/www/little-progress-server/little-progress.db /var/www/little-progress-server/backup-$(date +%Y%m%d).db

# 查看数据库大小
ls -lh /var/www/little-progress-server/little-progress.db
```

## 故障排查

### 服务起不来

```bash
# 查看详细错误
journalctl -u little-progress --no-pager -n 50

# 常见原因：
# 1. venv 路径不对（目录改名后需更新 venv/bin/* 中的 shebang）
#    修复：sed -i 's|old-path|new-path|g' venv/bin/*
# 2. 端口被占用：ss -tlnp | grep 8000
# 3. SQLite 数据库锁定：删除 little-progress.db 或从备份恢复
```

### 网站打不开（ERR_CONNECTION_REFUSED）

```bash
# 检查 Nginx 是否运行
systemctl status nginx

# 检查端口
ss -tlnp | grep -E '80|443'

# 检查后端
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/

# 检查腾讯云安全组是否开放了 80/443 端口
```

### HTTPS 证书问题

```bash
# 查看证书到期时间
certbot certificates

# 强制续期测试
certbot renew --dry-run
```

### 访问码验证失败

```bash
# 测试接口
curl -s http://localhost:8000/api/login -X POST \
  -H "Content-Type: application/json" \
  -d '{"user_id":"me","code":"正确密码"}'

# 预期结果：
# - 密码错误 → {"detail":"访问码错误"} HTTP 403
# - 密码正确 → {"user":{"id":"me",...}} HTTP 200
```

## ❌ 不要做的事

- 不要直接 `kill -9` uvicorn 进程 —— 用 `systemctl restart little-progress`
- 不要手动编辑 SQLite 数据库文件 —— 用 API 操作
- 不要在 `nginx -t` 报错时 reload nginx
- 不要用默认密码 `admin123` 在生产环境
- 不要删除 `little-progress.db` 除非确认有备份
