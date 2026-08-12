#!/usr/bin/env bash
# ==========================================
# P6-1 更新部署（等价于 deploy.sh）
# 用法：bash deploy/scripts/update.sh [branch]
# ==========================================
set -euo pipefail
exec bash "$(dirname "$0")/deploy.sh" "$@"
