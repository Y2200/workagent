#!/usr/bin/env bash
# ==========================================
# P6-2 更新部署（等价于 deploy.sh）
# 用法：IMAGE_TAG=<commit-sha> bash deploy/scripts/update.sh
# ==========================================
set -euo pipefail
exec bash "$(dirname "$0")/deploy.sh" "$@"
