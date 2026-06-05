---
name: little-progress-ops
description: "运维 Little Progress 服务器：查看状态、部署更新、配置 SSL、管理访问码。用于日常运维排查与部署。触发词：服务器状态、部署、重启、日志、SSL、nginx、systemd"
---

# Little Progress 服务器运维

> 基于 Ubuntu 24.04 + Nginx + systemd + uvicorn 的 FastAPI 应用运维指南。

## 快速开始

> 第一次连这台服务器？先配好 SSH。

```bash
# 本地生成密钥（如果没有的话）
ssh-keygen -t ed25519 -f ~/.ssh/little-progress -N ""

# 把公钥添加到服务器
ssh-copy-id -i ~/.ssh/little-progress.pub root@43.153.155.195

# 本地配置 SSH 别名（方便后续使用）
cat >> ~/.ssh/config << 'EOF'
Host little-progress-root
  HostName 43.153.155.195
  User root
  IdentityFile ~/.ssh/little-progress
  StrictHostKeyChecking no
EOF

# 测试连接
ssh little-progress-root "hostname"
# 预期输出：VM-0-4-ubuntu
```

配好后用 `ssh little-progress-root` 登录。

### 服务管理（每日运维）

```bash
systemctl status little-progress   # 查看状态
systemctl start little-progress     # 启动
systemctl stop little-progress      # 停止
systemctl restart little-progress   # 重启
journalctl -u little-progress -f -n 50   # 实时日志
journalctl -u little-progress --no-pager -n 100  # 最近日志
```

## Step 1: 部署更新

> 本地改完代码推送后，在服务器上执行。

```bash
# Step 1a: 拉取最新代码
cd /var/www/little-progress-server
git pull origin main

# Step 1b: 重启服务
systemctl restart little-progress
```

或使用 update.sh：

```bash
bash /var/www/little-progress-server/update.sh
```

```bash
# 完整部署预期输出
cd /var/www/little-progress-server
git pull origin main
# Updating a1b2c3d..e4f5g6h
# Fast-forward
#  main.py | 2 +-
#  1 file changed, 1 insertion(+), 1 deletion(-)

systemctl restart little-progress
# 无输出（静默成功）

# 验证
sleep 2 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
# 200
```

**🔴 CHECKPOINT**：部署前确认已在本地 `git push` 成功。如果 git pull 报冲突，先 `git stash` 再试。

### 部署失败处理

| 症状 | 一线修复 | 仍失败兜底 |
|------|---------|-----------|
| `git pull` 报 local changes 冲突 | `git stash` 暂存 → 再 pull → `git stash pop` | 手动备份后 `git reset --hard origin/main` |
| 重启后服务仍为旧版本 | `git log --oneline -3` 确认 commit 是否最新 | `git fetch origin && git reset --hard origin/main` |
| 重启后服务起不来 | `journalctl -u little-progress -n 50` 看错误 | 见下方「服务起不来」故障表 |

## Step 2: 修改访问码 / 环境变量

**🔴 CHECKPOINT**：改环境变量前先确认当前值，避免改完自己连不上。

```bash
# 查看当前访问码
cat /etc/systemd/system/little-progress.service | grep Environment | grep ACCESS

# Step 2a: 编辑 systemd service
vi /etc/systemd/system/little-progress.service
# 在 [Service] 段添加或修改：
# Environment=MB_ACCESS_CODE=新密码

# Step 2b: 重新加载配置并重启
systemctl daemon-reload
systemctl restart little-progress
```

### 环境变量表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MB_ADMIN_PASSWORD` | `admin123` | 管理后台登录密码 |
| `MB_ACCESS_CODE` | `xiaojinbu2025` | 前端访问码（用户打开页面时输入） |

**🔴 CHECKPOINT**：改完重启后，先用 curl 测试新密码是否生效，再通知用户：

```bash
curl -s http://localhost:8000/api/login -X POST \
  -H "Content-Type: application/json" \
  -d '{"user_id":"me","code":"新密码"}'
# 返回 {"user":{...}} HTTP 200 → 生效
# 返回 {"detail":"访问码错误"} HTTP 403 → 未生效，检查配置
```

## Step 3: Nginx 配置修改

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

**🔴 CHECKPOINT**：修改后必须先用 `nginx -t` 验证语法，再 reload。语法错误直接 reload 会导致 nginx 挂掉。修改前建议备份当前配置：

```bash
cp /etc/nginx/sites-available/little-progress /etc/nginx/sites-available/little-progress.bak
```

```bash
nginx -t                     # 语法检查（必须返回 syntax is ok + test successful）
systemctl reload nginx        # 只有上面成功后执行
```

### Nginx 修改失败处理

| 症状 | 一线修复 | 仍失败兜底 |
|------|---------|-----------|
| `nginx -t` 报语法错误 | 检查分号遗漏、括号不匹配、`server_name` 拼写 | `cp /etc/nginx/sites-available/little-progress.bak` 恢复上次备份 |
| reload 后网站 502 | 检查 uvicorn 是否在运行 `systemctl status little-progress` | `systemctl restart little-progress` 先重启后端 |
| reload 后 HTTPS 不生效 | 检查证书路径是否存在 `ls -la /etc/letsencrypt/live/` | `certbot renew` 重新签发证书 |

## Step 4: SSL 证书管理

使用 Let's Encrypt（Certbot），证书信息：

```
域名：little-progress.cloud, www.little-progress.cloud
路径：/etc/letsencrypt/live/little-progress.cloud/
到期：自动续期（certbot systemd timer 每天检查，到期前 30 天续签）
```

```bash
# 查看证书状态
certbot certificates

# 强制续期测试（不会真的续，只验证流程）
certbot renew --dry-run

# 手动续期（一般不需要）
certbot renew

# 申请新证书（首次或加域名）
certbot certonly --nginx -d little-progress.cloud -d www.little-progress.cloud
```

### 证书问题处理

| 症状 | 一线修复 | 仍失败兜底 |
|------|---------|-----------|
| 浏览器提示证书不安全 | `certbot certificates` 检查是否过期 | `certbot renew` 强制续期 |
| 续期失败（端口被占） | 确保 80 端口可访问 `ss -tlnp \| grep :80` | `systemctl stop nginx && certbot renew && systemctl start nginx` |
| 新域名访问 HTTPS 异常 | 检查域名 DNS 是否指向本机 IP | 加域名到 certbot：`certbot --expand -d old.com -d new.com` |

## 服务架构

```
客户端 → Nginx (80/443) → proxy_pass → uvicorn (127.0.0.1:8000) → FastAPI → SQLite
```

| 层 | 技术 | 端口 |
|----|------|------|
| 反向代理 | Nginx 1.24 | 80 (HTTP) / 443 (HTTPS) |
| Web 服务 | uvicorn + FastAPI | 127.0.0.1:8000 |
| 数据库 | SQLite | 文件：`/var/www/little-progress-server/little-progress.db` |

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

## 数据库

```bash
# 备份
cp /var/www/little-progress-server/little-progress.db \
   /var/www/little-progress-server/backup-$(date +%Y%m%d).db

# 查看大小
ls -lh /var/www/little-progress-server/little-progress.db
```

## 故障排查（if-then 表）

### 服务起不来

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| `systemctl status` 显示 failed | `journalctl -u little-progress -n 50` 看具体错误 | `systemctl restart little-progress` 重试 |
| 错误含 `status=203/EXEC` | venv 路径不对 → 检查 shebang：`head -1 venv/bin/uvicorn` | `sed -i 's|旧路径|新路径|g' venv/bin/*` 修复 shebang |
| 错误含 `Address already in use` | 端口被占用 → `ss -tlnp \| grep 8000` 查占用进程 | `kill` 占用进程或换端口 |
| SQLite 数据库锁定错误 | `ls -l \*.db` 检查是否有 `.db-wal` 或 `.db-shm` | 从备份恢复或删除这两个文件 |

### 网站打不开（ERR_CONNECTION_REFUSED）

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| 浏览器显示 ERR_CONNECTION_REFUSED | `systemctl status nginx` 检查 Nginx 是否运行 | `systemctl start nginx` 启动 |
| Nginx 运行但 80 端口不通 | `ss -tlnp \| grep ':80'` 确认监听 | `nginx -t && systemctl reload nginx` |
| Nginx 正常但后端不通 | `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/` | `systemctl restart little-progress` |
| 服务端正常但外部无法访问 | 腾讯云安全组未开放 80/443 端口 | 登录腾讯云控制台 → 安全组 → 添加入站规则 |

### HTTPS 证书问题

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| 浏览器提示证书过期 | `certbot certificates` 查看到期日 | `certbot renew` 强制续期 |
| 访问 `www` 域名证书不匹配 | 检查证书是否包含 `www`：`certbot certificates` | `certbot --expand -d domain -d www.domain` 添加域名 |
| certbot 续期失败 | `certbot renew --dry-run` 测试 | 检查 80 端口是否被防火墙阻断 |

### 访问码验证失败

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| 用户登录提示"访问码错误" | `curl -s http://localhost:8000/api/login -X POST -H 'Content-Type: application/json' -d '{"user_id":"me","code":"当前密码"}'` | 检查环境变量 `cat /etc/systemd/system/little-progress.service \| grep ACCESS` |
| curl 测试返回 403 | 返回 `{"detail":"访问码错误"}` → 密码不匹配，检查 `MB_ACCESS_CODE` | 用默认密码 `xiaojinbu2025` 试，或查看 main.py 中默认值 |
| curl 返回 404 | 返回 `{"detail":"User not found"}` → 数据库用户丢失 | 重启服务自动重建：`systemctl restart little-progress` |

## ❌ 不要做的事（按严重程度）

### 🔴 危险（可能丢数据或服务宕机）

- 不要 `kill -9` uvicorn 进程 → 用 `systemctl restart little-progress`
- 不要在 `nginx -t` 报错时 reload nginx → 先修语法错误
- 不要删除 `little-progress.db` 除非确认有备份
- 不要手动编辑 SQLite 数据库 → 用 API 操作

### 🟡 警告（安全风险）

- 不要用默认密码 `admin123` 在生产环境
- 不要用默认访问码 `xiaojinbu2025` 在面向公众的环境
- 不要关闭 `ufw` 防火墙（如果已启用）

### 🔵 注意（运维规范）

- 不要直接在服务器上编辑代码 → 本地改完 git push 后部署
- 不要跳过 `nginx -t` 直接 reload
- 不要在业务高峰期部署

## 参考文件

| 路径 | 用途 |
|------|------|
| `/var/www/little-progress-server/deploy.sh` | 一键部署脚本 |
| `/var/www/little-progress-server/update.sh` | 更新脚本 |
| `/etc/systemd/system/little-progress.service` | systemd 服务配置 |
| `/etc/nginx/sites-available/little-progress` | Nginx 站点配置 |
| `/etc/letsencrypt/live/little-progress.cloud/` | SSL 证书目录 |
| `/var/www/little-progress-server/little-progress.db` | SQLite 数据库 |
