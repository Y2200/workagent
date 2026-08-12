#!/usr/bin/env bash
# ==========================================
# P6-1 回滚到 deploy/.last_deploy 记录的上一版本
#   检出上一提交的代码 → 重建后端 → 重建前端 → reload nginx
# 注意：会丢弃未提交的业务代码改动（先确认/备份）
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

test -f deploy/.last_deploy || { echo "✗ 无回滚记录（deploy/.last_deploy）"; exit 1; }
TARGET="$(cat deploy/.last_deploy)"
echo "回滚目标提交：$TARGET"

echo "===== 1. 检出上一版本代码（保留未跟踪的 deploy/ 与 .env）====="
git stash push --include-untracked -m "rollback-before" 2>/dev/null || true
git checkout "$TARGET" -- src frontend/src frontend/package.json frontend/vite.config.js 2>/dev/null \
  || { echo "✗ 检出失败"; git stash pop 2>/dev/null || true; exit 1; }

echo "===== 2. 重建前端 ====="
cd frontend
npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
npm run build
cd "$REPO_ROOT"
# 注：构建产物即 nginx 根目录（仓库内 frontend/dist），无需拷贝

echo "===== 3. 重建并重启后端 ====="
docker compose -f deploy/docker-compose.prod.yml --env-file .env build backend
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d

echo "===== 4. Nginx reload ====="
$SUDO nginx -t && $SUDO systemctl reload nginx

echo ""
echo "回滚完成。如需回到新版本：bash deploy/scripts/deploy.sh"
