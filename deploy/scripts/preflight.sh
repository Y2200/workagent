#!/usr/bin/env bash
# ==========================================
# P6-2 部署前检查（幂等，可重复执行）
#   1 源码/敏感文件泄露检查（仅当存在 Git 工作区）
#   2 docker / docker compose 可用
#   3 .env 存在
#   4 磁盘空间 / 内存
#   5 宿主机 Nginx 必须已停用（方案B：与 frontend 容器抢 80/443）
#   6 80/443 端口状态
#   7 证书目录与 ACME 目录就绪（frontend 容器的挂载源）
# ==========================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# 证书目录（与 docker-compose.prod.yml 中的挂载源保持一致）
CERT_CONF="${CERTBOT_CONF_DIR:-/opt/work-agent/certbot/conf}"
CERT_WWW="${CERTBOT_WWW_DIR:-/opt/work-agent/certbot/www}"

fail() { echo "✗ $*"; exit 1; }

echo "===== 1. 敏感文件检查 ====="
if [ -d .git ]; then
  if git ls-files 2>/dev/null | grep -E '(^|/)\.env$|\.env\.(local|prod|dev|stage)|secret|credential|\.key$|\.pem$|\.crt$'; then
    echo "✗ 发现敏感文件被 Git 跟踪！停止部署，先处理。"
    exit 1
  fi
  echo "✓ Git 中无 .env / 密钥"
else
  echo "✓ 无 Git 工作区（P6-2：生产服务器不保存源码）"
fi

echo ""
echo "===== 2. Docker ====="
docker version --format 'Server {{.Server.Version}}' 2>/dev/null || fail "docker 不可用，先运行 init-server.sh"

echo ""
echo "===== 3. docker compose ====="
docker compose version 2>/dev/null || fail "docker compose 不可用"

echo ""
echo "===== 4. .env ====="
test -f .env || fail "缺少 .env，请按 deploy/README.md 创建"
echo "✓ .env 存在（已 gitignore，不入库）"

echo ""
echo "===== 5. 磁盘空间 ====="
df -h / | awk 'NR==1 || NR==2{print}'

echo ""
echo "===== 6. 内存 ====="
free -h | head -2

echo ""
echo "===== 7. 宿主机 Nginx（方案B：必须已停用）====="
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet nginx 2>/dev/null; then
  echo "✗ 宿主机 nginx 仍在运行，会与 frontend 容器抢占 80/443"
  echo "  一次性切换：sudo systemctl stop nginx && sudo systemctl disable nginx"
  exit 1
fi
echo "✓ 宿主机无 nginx 运行（或未安装）"

echo ""
echo "===== 8. 80/443 端口状态 ====="
# 切换后常态：80/443 由本项目的 frontend 容器经 docker-proxy 占用 → 正常
# 只有被**宿主机 Web 服务器**占用才是异常（会与 frontend 容器抢端口）
LISTEN_ENTRIES="$(ss -ltnp 2>/dev/null | grep -E ':(80|443)\s' || true)"
if [ -z "$LISTEN_ENTRIES" ]; then
  echo "⚠  80/443 空闲——若 frontend 容器已在运行，请确认它是否真的接管了入口"
elif echo "$LISTEN_ENTRIES" | grep -q 'docker-proxy'; then
  echo "✓ 80/443 由 docker-proxy（本项目的 frontend 容器）占用"
elif echo "$LISTEN_ENTRIES" | grep -qE '"(nginx|httpd|apache2)"'; then
  echo "✗ 80/443 被宿主机 Web 服务器占用，会与 frontend 容器冲突："
  echo "$LISTEN_ENTRIES"
  echo "  处理：sudo systemctl stop nginx && sudo systemctl disable nginx"
  exit 1
else
  echo "⚠  80/443 已被占用，但无法确认占用者（非 root 时看不到进程名）："
  echo "$LISTEN_ENTRIES"
fi

echo ""
echo "===== 9. 证书目录（frontend 容器挂载源）====="
test -f "$CERT_CONF/live/wkcp.online/fullchain.pem" \
  || fail "缺少证书 $CERT_CONF/live/wkcp.online/fullchain.pem（首次切换见 deploy/README.md）"
test -f "$CERT_CONF/live/wkcp.online/privkey.pem" \
  || fail "缺少私钥 $CERT_CONF/live/wkcp.online/privkey.pem（同上）"
test -d "$CERT_WWW" || fail "缺少 ACME webroot 目录 $CERT_WWW"
echo "✓ 证书与 ACME 目录就绪"

echo ""
echo "===== 预检通过，可部署 ====="
