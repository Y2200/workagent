#!/usr/bin/env bash
# ==========================================
# P6-1 部署前检查（幂等，可重复执行）
#   - git 中无 .env / 敏感文件
#   - docker / docker compose 可用
#   - 磁盘空间 / 内存
#   - 80/443 端口状态
# ==========================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

fail() { echo "✗ $*"; exit 1; }

echo "===== 1. Git 敏感文件检查 ====="
if git ls-files 2>/dev/null | grep -E '(^|/)\.env$|\.env\.(local|prod|dev|stage)|secret|credential|\.key$|\.pem$|\.crt$' ; then
  echo "✗ 发现敏感文件被 Git 跟踪！停止部署，先处理。"
  exit 1
fi
echo "✓ Git 中无 .env / 密钥"
git status --short | head -5 || true

echo ""
echo "===== 2. Docker ====="
docker version --format 'Server {{.Server.Version}}' 2>/dev/null || fail "docker 不可用，先运行 init-server.sh"

echo ""
echo "===== 3. docker compose ====="
docker compose version 2>/dev/null || fail "docker compose 不可用"

echo ""
echo "===== 4. 磁盘空间 ====="
df -h / | awk 'NR==1 || NR==2{print}'

echo ""
echo "===== 5. 内存 ====="
free -h | head -2

echo ""
echo "===== 6. 80/443 端口状态 ====="
if ss -ltn 2>/dev/null | grep -E ':(80|443)\s'; then
  echo "⚠  80/443 已被占用——确认是 Nginx（本系统部署目标）"
else
  echo "✓ 80/443 空闲"
fi

echo ""
echo "===== 预检通过，可部署 ====="
