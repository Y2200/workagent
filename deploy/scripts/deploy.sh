#!/usr/bin/env bash
# ==========================================
# P6-2 生产部署（幂等，可重复执行）
#   镜像来自 Docker Hub；服务器**不构建、不 git pull**
#
#   流程：预检 → 校验变量 → pull 应用镜像 → up -d → 等后端就绪
#         → 幂等迁移/种子 → 记录版本 → 健康检查
#
# 用法：
#   IMAGE_TAG=<commit-sha> bash deploy/scripts/deploy.sh
#   （CI/CD 由 .github/workflows/ci.yml 的 deploy job 调用并注入 IMAGE_TAG）
#
# 前提：
#   - .env 存在且已配置 DOCKERHUB_USER 与全部生产变量
#   - /opt/work-agent/certbot/{conf,www} 就绪（preflight 会校验）
#   - 宿主机 Nginx 已停用（方案B：Web 入口由 frontend 容器承担）
# ==========================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="deploy/docker-compose.prod.yml"
ENV_FILE=".env"
COMPOSE="docker compose -f $COMPOSE_FILE --env-file $ENV_FILE"

echo "===== 0. 预检 ====="
bash deploy/scripts/preflight.sh

echo ""
echo "===== 1. 校验部署变量 ====="
: "${IMAGE_TAG:?请注入镜像版本：IMAGE_TAG=<commit-sha> bash deploy/scripts/deploy.sh}"
test -f "$ENV_FILE" || { echo "✗ 缺少 $ENV_FILE，请按 deploy/README.md 创建"; exit 1; }
if ! grep -qE '^DOCKERHUB_USER=.+' "$ENV_FILE" && [ -z "${DOCKERHUB_USER:-}" ]; then
  echo "✗ 未配置 DOCKERHUB_USER（写入 $ENV_FILE，或由 CI 注入环境变量）"
  exit 1
fi
export IMAGE_TAG
if [ -n "${DOCKERHUB_USER:-}" ]; then export DOCKERHUB_USER; fi
echo "✓ IMAGE_TAG=$IMAGE_TAG"

echo ""
echo "===== 2. 拉取应用镜像（仅 frontend/backend；基础设施不动）====="
$COMPOSE pull backend frontend

echo ""
echo "===== 3. 启动/更新全部服务 ====="
$COMPOSE up -d

echo ""
echo "===== 4. 等待 backend 就绪 ====="
# P6-2 起 backend 不再发布宿主机端口，健康检查在容器内执行
for i in $(seq 1 30); do
  if $COMPOSE exec -T backend curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "✓ backend healthy（${i} 次尝试）"
    break
  fi
  [ "$i" -eq 30 ] && { echo "✗ backend 60s 内未就绪，查 docker logs work-agent-backend"; exit 1; }
  sleep 2
done

echo ""
echo "===== 4.5 让 Nginx 重新解析后端地址（防御性）====="
# 正常发版前后端容器会同时重建，Nginx 天然拿到新 IP；
# 但若只重建了 backend（例如手动 `up -d backend`），Nginx 会继续用缓存的旧 IP，
# 导致 /api 持续 502 —— 这里补一次 reload（幂等、无副作用；失败不阻断部署）
if $COMPOSE exec -T frontend nginx -s reload 2>/dev/null; then
  echo "✓ Nginx 已 reload"
else
  echo "⚠  reload 未成功（容器可能仍在启动）。若 /api 返回 502，手动执行："
  echo "   docker compose -f $COMPOSE_FILE --env-file $ENV_FILE exec -T frontend nginx -s reload"
fi

echo ""
echo "===== 5. 幂等迁移 + 种子（每次部署安全重跑；不含测试数据）====="
run_migration() {
  echo "  >> $1"
  $COMPOSE exec -T backend python -m "work_agent.scripts.$1"
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
echo "===== 6. 记录当前部署版本（回滚依据）====="
echo "$IMAGE_TAG" > deploy/.last_deploy
echo "$IMAGE_TAG" >> deploy/.deploy_history
echo "✓ 当前版本：$IMAGE_TAG"

echo ""
echo "===== 7. 健康检查 ====="
$COMPOSE ps
if $COMPOSE exec -T frontend wget -q -O /dev/null http://127.0.0.1/healthz; then
  echo "✓ Web 入口（frontend 容器）存活"
else
  echo "✗ frontend 未响应，查 docker logs work-agent-frontend"
  exit 1
fi

echo ""
echo "===== 部署完成 ====="
echo "回滚到上一版本：bash deploy/scripts/rollback.sh"
echo "回滚到指定版本：bash deploy/scripts/rollback.sh <IMAGE_TAG>"
