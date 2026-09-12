#!/usr/bin/env bash
# ==========================================
# P6-2 证书续期（certbot 容器签发/续期 + reload frontend 容器内的 Nginx）
#
#   由宿主机 systemd timer 每日调用（deploy/systemd/cert-renew.timer），
#   不挂 docker socket：续期由宿主机触发，容器只负责跑 certbot。
#
#   certbot renew 幂等：证书未临近过期则不动作（reload 无害）
#
# 用法：
#   bash deploy/scripts/renew-cert.sh            # 正常续期检查 + reload
#   bash deploy/scripts/renew-cert.sh --dry-run  # 演练（不续期、不 reload）
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# compose 会对**整个文件**做变量插值（与你只跑哪个服务无关），
# 而 systemd 调用本脚本时环境里没有 IMAGE_TAG → 不补上会直接插值失败、续期静默失效。
# 注意：本脚本只跑 certbot 容器，不启动 frontend/backend，故该值仅用于满足插值。
if [ -z "${IMAGE_TAG:-}" ]; then
  export IMAGE_TAG="$(cat deploy/.last_deploy 2>/dev/null || echo none)"
fi

COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file .env --profile certbot"

if [ "${1:-}" = "--dry-run" ]; then
  echo "===== dry-run：演练续期（不实际签发）====="
  $COMPOSE run --rm certbot renew --webroot -w /var/www/certbot --dry-run
  echo "✓ dry-run 通过（未实际续期、未 reload）"
  exit 0
fi

echo "===== 1. certbot renew ====="
$COMPOSE run --rm certbot renew --webroot -w /var/www/certbot

echo ""
echo "===== 2. reload frontend 容器内的 Nginx（加载新证书）====="
$COMPOSE exec -T frontend nginx -s reload

echo ""
echo "✓ 续期检查完成"
