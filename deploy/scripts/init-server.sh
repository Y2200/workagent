#!/usr/bin/env bash
# ==========================================
# P6-1 腾讯云 Ubuntu 服务器初始化（幂等）
#   安装 docker / nginx / certbot / ufw
#   防火墙仅放行 22 / 80 / 443
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
echo "===== 2. 安装 nginx / certbot / ufw ====="
$SUDO apt-get install -y nginx certbot python3-certbot-nginx ufw

echo ""
echo "===== 3. 防火墙：仅开放 22/80/443 ====="
$SUDO ufw allow 22/tcp
$SUDO ufw allow 80/tcp
$SUDO ufw allow 443/tcp
$SUDO ufw --force enable
$SUDO ufw status verbose

echo ""
echo "===== 4. 当前用户加入 docker 组 ====="
$SUDO usermod -aG docker "$USER" || true
echo "（重新登录后 docker 无需 sudo）"

echo ""
echo "服务器初始化完成。下一步："
echo "  1) 上传代码到服务器"
echo "  2) 参考 deploy/README.md 创建 .env"
echo "  3) 执行 deploy/scripts/deploy.sh"
