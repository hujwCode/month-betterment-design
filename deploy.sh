#!/bin/bash
# Little Progress - 服务器部署脚本
# 在 Ubuntu 服务器上以 root 或 ubuntu 用户运行

set -e

echo "🌿 开始部署 Little Progress"

# 1. 安装依赖
echo "📦 安装 Python 依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv

# 2. 备份数据（数据库 + 配置文件）
echo "💾 备份数据..."
DB_BACKUP=""
if [ -f /var/www/little-progress-server/little-progress.db ]; then
  cp /var/www/little-progress-server/little-progress.db /tmp/little-progress.db.bak
  echo "  ✅ 数据库已备份"
fi

# 3. 拉取代码
echo "📥 拉取最新代码..."
cd /var/www
if [ -d little-progress-server ]; then
  sudo rm -rf little-progress-server
fi
sudo git clone https://github.com/hujwCode/little-progress-server.git little-progress-server
sudo chown -R ubuntu:ubuntu little-progress-server
cd little-progress-server

# 4. 恢复数据
echo "♻️  恢复数据..."
if [ -f /tmp/little-progress.db.bak ]; then
  mv /tmp/little-progress.db.bak little-progress.db
  echo "  ✅ 数据库已恢复"
  chown ubuntu:ubuntu little-progress.db
fi

# 5. 创建虚拟环境并安装
echo "🐍 配置 Python 环境..."
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# 6. 创建 systemd 服务
echo "⚙️ 创建 systemd 服务..."
sudo tee /etc/systemd/system/little-progress.service > /dev/null << 'SERVICE'
[Unit]
Description=Little Progress FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/little-progress-server
ExecStart=/var/www/little-progress-server/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

# 7. 更新 nginx 配置
echo "🌐 更新 Nginx 配置..."
sudo tee /etc/nginx/sites-available/little-progress > /dev/null << 'NGINX'
server {
    listen 80;
    server_name 43.153.155.195;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/little-progress /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# 8. 启动后端服务
echo "🚀 启动后端服务..."
sudo systemctl daemon-reload
sudo systemctl enable little-progress
sudo systemctl restart little-progress

# 9. 开放防火墙
echo "🔥 配置防火墙..."
sudo ufw allow 80/tcp 2>/dev/null || true
sudo ufw --force enable 2>/dev/null || true

echo ""
echo "========================"
echo "✅ 部署完成！"
echo "📱 打卡前端: http://43.153.155.195/"
echo "📊 管理后台: http://43.153.155.195/admin.html"
echo "🔐 后台密码: admin123"
echo "========================"
echo ""
echo "查看运行状态: sudo systemctl status little-progress"
echo "查看实时日志: sudo journalctl -u little-progress -f"
