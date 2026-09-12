#!/usr/bin/env bash
# ==========================================
# P6-2 回滚：切换镜像版本（不重建、不 git）
#
#   bash deploy/scripts/rollback.sh              # 回上一版本（历史里最近的其它版本）
#   bash deploy/scripts/rollback.sh <IMAGE_TAG>  # 回指定版本
#
# 说明：
#   - 只切换 IMAGE_TAG 后 up -d，不在服务器构建，也不检出代码
#   - **不回滚数据库**：迁移不向后执行；schema 需人工处理
#   - 旧镜像若被 docker image prune -a 清掉，pull 会失败 ——
#     生产机请勿执行全量 prune；Docker Hub 上的历史 tag 已保留
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file .env"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  test -f deploy/.deploy_history \
    || { echo "✗ 无部署历史 deploy/.deploy_history，请显式指定：rollback.sh <IMAGE_TAG>"; exit 1; }
  CUR="$(cat deploy/.last_deploy 2>/dev/null || true)"
  TARGET="$(grep -v -x "$CUR" deploy/.deploy_history | tail -1)"
  [ -n "$TARGET" ] \
    || { echo "✗ 历史中找不到其它版本，请显式指定：rollback.sh <IMAGE_TAG>"; exit 1; }
fi

echo "===== 回滚目标：$TARGET ====="
export IMAGE_TAG="$TARGET"

echo ""
echo "===== 1. 拉取目标版本镜像 ====="
$COMPOSE pull backend frontend

echo ""
echo "===== 2. 切换版本并重启 ====="
$COMPOSE up -d

echo ""
echo "===== 3. 等待 backend 就绪 ====="
for i in $(seq 1 30); do
  if $COMPOSE exec -T backend curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "✓ backend healthy（${i} 次尝试）"
    break
  fi
  [ "$i" -eq 30 ] && { echo "✗ backend 未就绪，查 docker logs work-agent-backend"; exit 1; }
  sleep 2
done

echo ""
echo "===== 3.5 让 Nginx 重新解析后端地址 ====="
# 回滚会重建 backend 容器（新 IP），Nginx 缓存的旧 IP 会导致 /api 502
if $COMPOSE exec -T frontend nginx -s reload 2>/dev/null; then
  echo "✓ Nginx 已 reload"
else
  echo "⚠  reload 未成功；若 /api 返回 502，手动执行："
  echo "   docker compose -f deploy/docker-compose.prod.yml --env-file .env exec -T frontend nginx -s reload"
fi

echo ""
echo "===== 4. 记录回滚 ====="
echo "$TARGET" > deploy/.last_deploy
echo "$TARGET" >> deploy/.deploy_history

echo ""
echo "✓ 已回滚到 $TARGET"
echo "  注意：数据库未回滚（迁移不向后执行）"
