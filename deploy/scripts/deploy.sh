#!/usr/bin/env bash
# ==========================================
# P6-1 生产部署（幂等，可重复执行）
#   预检 → git pull → 前端构建 → 拷贝 dist
#   → compose 构建/启动后端 → 等就绪 → 幂等迁移
#   → 记录版本 → Nginx reload
# 需在服务器仓库根执行；.env 位于仓库根
# CI/CD（.github/workflows/ci.yml deploy job）也调用本脚本
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

BRANCH="${1:-master}"

echo "===== 0. 预检 ====="
bash deploy/scripts/preflight.sh

echo ""
echo "===== 1. 拉取代码（${BRANCH}）====="
git fetch origin 2>/dev/null || true
if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH" || echo "（拉取失败，继续使用本地代码）"
else
  echo "（无 origin/$BRANCH，使用本地代码）"
fi

echo ""
echo "===== 2. 前端构建（npm run build）====="
cd frontend
npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
npm run build
cd "$REPO_ROOT"

echo ""
# 注：nginx 根目录即 /opt/work-agent/frontend/dist（仓库内），
# npm run build 产物已在目标位置，无需拷贝（旧版拷贝会自删 dist）
echo "===== 3. 校验生产 .env ====="
test -f .env || { echo "✗ 缺少 .env，请按 deploy/README.md 创建"; exit 1; }
echo "✓ .env 存在（已 gitignore，不入库）"

echo ""
echo "===== 4. 构建并启动后端 ====="
docker compose -f deploy/docker-compose.prod.yml --env-file .env build backend
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d

echo ""
echo "===== 5. 等待 backend 就绪 ====="
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "✓ backend healthy（${i} 次尝试）"
    break
  fi
  [ "$i" -eq 30 ] && { echo "✗ backend 60s 内未就绪，查 docker logs work-agent-backend"; exit 1; }
  sleep 2
done

echo ""
echo "===== 5.5 幂等迁移 + 种子（每次部署安全重跑；不含测试数据）====="
COMPOSE_P="docker compose -f deploy/docker-compose.prod.yml --env-file .env"
run_migration() {
  echo "  >> $1"
  $COMPOSE_P exec -T backend python -m "work_agent.scripts.$1"
}
run_migration init_db
run_migration seed_admin
run_migration migrate_agent_logs
run_migration migrate_agent_intelligence
run_migration migrate_user_profile
run_migration migrate_tasks
run_migration migrate_conversation_messages
run_migration migrate_indexes
run_migration seed_rbac

echo ""
echo "===== 6. 记录当前部署版本 ====="
git rev-parse HEAD > deploy/.last_deploy

echo ""
echo "===== 7. 更新 Nginx ====="
if [ -d /etc/nginx/conf.d ]; then
  $SUDO cp deploy/nginx/wkcp.online.conf /etc/nginx/conf.d/
  $SUDO cp deploy/nginx/api.wkcp.online.conf /etc/nginx/conf.d/
  $SUDO nginx -t
  $SUDO systemctl reload nginx
fi

echo ""
echo "===== 部署完成 ====="
echo "验证："
echo "  docker compose -f deploy/docker-compose.prod.yml ps   # 全部 healthy"
echo "  curl -fsS http://127.0.0.1:8000/health                # 后端存活"
echo "  首次部署后执行 deploy/scripts/init-prod.sh 初始化数据库与管理员"
