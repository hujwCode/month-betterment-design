#!/bin/bash
# DailyStep - 服务器更新脚本
# 在服务器上运行：bash update.sh

set -e

echo "🌿 正在更新一个月变好计划..."

cd /var/www/dailystep-server

echo "📥 拉取最新代码..."
sudo git pull origin main

echo "🚀 重启后端服务..."
sudo systemctl restart dailystep

echo ""
echo "========================"
echo "✅ 更新完成！"
echo "📱 打卡前端: http://43.153.155.195/"
echo "📊 管理后台: http://43.153.155.195/admin.html"
echo "========================"
