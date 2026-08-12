#!/usr/bin/env bash
# ==========================================
# P6-1 生产首次初始化（仅在第一次部署后执行一次）
#
# 允许执行（生产唯一初始化路径）：
#   - init_db（建表，幂等）
#   - 必要迁移（按需新增）
#   - seed_admin（用 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD 创建初始管理员）
#
# 禁止执行（测试数据绝不入生产）：
#   - seed_tenants
#   - seed_knowledge_library
#   - 任何测试/种子数据导入
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

test -f .env || { echo "✗ 缺少 .env"; exit 1; }

COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file .env"

echo "===== 检查后端已启动 ====="
$COMPOSE ps backend >/dev/null 2>&1 || { echo "✗ 后端未启动，请先执行 deploy.sh"; exit 1; }

echo "===== 1. init_db（建表，幂等）====="
$COMPOSE exec -T backend python -m work_agent.scripts.init_db

echo "===== 2. 必要迁移（按需新增）====="
# 示例（如未来引入）：$COMPOSE exec -T backend python -m work_agent.scripts.migrate_xxx

echo "===== 3. seed_admin（初始管理员）====="
$COMPOSE exec -T backend python -m work_agent.scripts.seed_admin

echo ""
echo "首次初始化完成（仅 init_db + seed_admin）。"
echo "后续更新只执行 deploy.sh / update.sh，不再重复 init-prod.sh。"
