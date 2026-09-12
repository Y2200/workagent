#!/usr/bin/env bash
# ==========================================
# P6-2 生产服务器初始化（幂等）
#   安装 docker / docker compose + ufw（防火墙仅放行 22 / 80 / 443）
#
#   方案B：Web 入口（Nginx + TLS 证书）已容器化，
#   宿主机**不再需要**安装 nginx / certbot。
# 需 root 或 sudo 执行
# ==========================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
  echo "请以 root 或具有 sudo 权限的用户执行"; exit 1
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "===== 1. 安装 Docker ====="
if command -v docker >/dev/null 2>&1; then
  echo "docker 已安装：$(docker --version)"
else
  $SUDO apt-get update
  $SUDO apt-get install -y docker.io docker-compose-v2
  $SUDO systemctl enable --now docker
fi

echo ""
echo "===== 2. 防火墙：仅开放 22/80/443 ====="
$SUDO apt-get install -y ufw
$SUDO ufw allow 22/tcp
$SUDO ufw allow 80/tcp
$SUDO ufw allow 443/tcp
$SUDO ufw --force enable
$SUDO ufw status verbose

echo ""
echo "===== 3. 当前用户加入 docker 组 ====="
$SUDO usermod -aG docker "$USER" || true
echo "（重新登录后 docker 无需 sudo）"

echo ""
echo "===== 4. 准备部署目录与证书目录 ====="
$SUDO mkdir -p /opt/work-agent/certbot/conf /opt/work-agent/certbot/www
echo "✓ /opt/work-agent/certbot/{conf,www} 就绪"

echo ""
echo "===== 5. 检查宿主机 Nginx（方案B 需停用）====="
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet nginx 2>/dev/null; then
  echo "⚠  宿主机 nginx 正在运行，会与 frontend 容器抢占 80/443"
  echo "   完成证书迁移后再停用：sudo systemctl stop nginx && sudo systemctl disable nginx"
else
  echo "✓ 宿主机无 nginx 运行（或未安装）"
fi

echo ""
echo "服务器初始化完成。下一步（详见 deploy/README.md）："
echo "  1) 创建 /opt/work-agent/.env（含 DOCKERHUB_USER 与全部生产变量）"
echo "  2) 迁移证书到 /opt/work-agent/certbot/conf，并把续期方式改为 webroot"
echo "  3) 安装续期 timer：sudo cp deploy/systemd/cert-renew.* /etc/systemd/system/"
echo "     sudo systemctl daemon-reload && sudo systemctl enable --now cert-renew.timer"
echo "  4) 等 CI 推送部署制品后执行：IMAGE_TAG=<sha> bash deploy/scripts/deploy.sh"
