# P6-2 生产部署手册（容器化：CI 构建镜像 → Docker Hub → CD 只拉镜像）

**本文件为服务器执行步骤，不含任何凭据。** 域名 `wkcp.online`。

```
                 Internet
                    │ 80 / 443
                    ▼
        ┌───────────────────────────┐
        │  frontend 容器             │  ← 唯一对外发布端口的服务
        │  Nginx + Vue dist         │     TLS 终止（Let's Encrypt 证书卷）
        │                           │
        │  /            → 容器内 dist
        │  /api/        → backend:8000
        │  /health      → backend:8000/health
        └───────────┬───────────────┘
                    │ Docker internal 网络（服务名互访）
   ┌────────────────┼─────────────────────────────────┐
   ▼                ▼                                 ▼
backend          postgres / redis              milvus(-etcd/-minio) / work-minio
（不发布端口）    （不发布端口，数据卷持久化）     （不发布端口，数据卷持久化）

宿主机只装：Docker + Docker Compose + ufw
（无 Nginx、无 Certbot、无 Git 工作区、无源码/Node）
```

## 核心原则（P6-2 改造后）

| | 说明 |
|--|--|
| **服务器不构建** | 镜像全部由 GitHub Actions 构建并推送 Docker Hub；服务器只 `docker compose pull` |
| **服务器无源码** | CI 用 scp 把 `deploy/` 制品（compose + nginx 配置 + 脚本）推到 `/opt/work-agent/` |
| **配置即代码** | Nginx 配置在镜像里 → **改配置 = 改代码 = 走一次发版**，不再在服务器上 cp 配置 |
| **版本可追溯** | 镜像 tag = commit 全 SHA；部署后写入 `deploy/.last_deploy`（回滚依据） |
| **Web 入口容器化** | 宿主机 Nginx/Certbot 已停用；TLS 由 frontend 容器承担，证书走宿主机卷 |

---

# 一、首次上线：服务器一次性切换

> ⚠️ 本次切换需要一次**停机窗口**（约 1–3 分钟，建议低峰执行）。
> 顺序经过设计：**能提前做的都不占停机时间**，停机只覆盖「停宿主机 Nginx → 起容器」。

## 前置（在你本地 / GitHub 上做）

1. **Docker Hub 建两个仓库**：`<用户名>/workagent-backend`、`<用户名>/workagent-frontend`
   （private 也可以，但服务器需要先 `docker login`，见第 5 步）
2. **GitHub Secrets**（`Y2200/workagent` → Settings → Secrets and variables → Actions）：

| Secret | 值 |
|--------|-----|
| `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` | 已有，无需改动 |
| `LLM_API_KEY` | 已有，无需改动 |
| `DOCKER_USERNAME` | Docker Hub 用户名 |
| `DOCKER_PAT` | Docker Hub **Personal Access Token**（勿用账号密码） |

3. **`deploy/scripts/init-server.sh`**：新服务器才需要跑（`sudo bash deploy/scripts/init-server.sh`）。
   > P6-2 起该脚本**不再安装 nginx/certbot**（已容器化）。

## 步骤 1：服务器上做「不停机」准备

```bash
ssh <DEPLOY_USER>@<服务器IP>

# 1.1 证书目录 + 从宿主机迁移现有证书（不重新签发，避免撞 Let's Encrypt 每周 5 次限流）
sudo mkdir -p /opt/work-agent/certbot/conf /opt/work-agent/certbot/www
sudo cp -a /etc/letsencrypt/. /opt/work-agent/certbot/conf/
sudo cp -a /var/www/certbot/. /opt/work-agent/certbot/www/ 2>/dev/null || true

# 1.2 验证符号链接完整（必须是 -> ../../archive/... 且能解析）
ls -l /opt/work-agent/certbot/conf/live/wkcp.online/
sudo test -f /opt/work-agent/certbot/conf/live/wkcp.online/fullchain.pem && echo "✓ 证书可读"
```

```bash
# 1.3 续期方式：nginx → webroot（容器内 nginx 无法被宿主机 certbot 驱动）
sudo cp /opt/work-agent/certbot/conf/renewal/wkcp.online.conf \
        /opt/work-agent/certbot/conf/renewal/wkcp.online.conf.bak
sudo sed -i 's/^authenticator = nginx/authenticator = webroot/' \
     /opt/work-agent/certbot/conf/renewal/wkcp.online.conf
# installer = nginx 必须删掉：否则 renew 时会尝试驱动宿主机的 nginx
sudo sed -i '/^installer = nginx/d' \
     /opt/work-agent/certbot/conf/renewal/wkcp.online.conf
# 追加 webroot 路径与域名映射（[renewalparams] 段内 + 文件末尾）
sudo grep -q '^webroot_path' /opt/work-agent/certbot/conf/renewal/wkcp.online.conf || \
  sudo sed -i '/^\[renewalparams\]/a webroot_path = /var/www/certbot,' \
       /opt/work-agent/certbot/conf/renewal/wkcp.online.conf
sudo grep -q '^\[\[webroot_map\]\]' /opt/work-agent/certbot/conf/renewal/wkcp.online.conf || \
  sudo tee -a /opt/work-agent/certbot/conf/renewal/wkcp.online.conf >/dev/null <<'EOF'

[[webroot_map]]
wkcp.online = /var/www/certbot
api.wkcp.online = /var/www/certbot
EOF
```

```bash
# 1.4 .env 必填项：加一行 Docker Hub 用户名（非密钥）
grep -q '^DOCKERHUB_USER=' /opt/work-agent/.env || \
  echo 'DOCKERHUB_USER=<你的 Docker Hub 用户名>' | sudo tee -a /opt/work-agent/.env
```

## 步骤 2：触发一次 CI，把镜像推到 Docker Hub

GitHub → Actions → CI/CD → **Run workflow**（选 master）。

- `test` job 必须绿（门禁）
- `build` job 会把前后端镜像推到 Docker Hub（backend 首次构建含 torch/ML 依赖，约 10–15 分钟；后续有 GHA 缓存会快很多）
- `deploy` job 此时**会失败**——预期之内：scp 步骤已把 `deploy/` 制品推到服务器（✔ 这正是我们要的），
  随后的 SSH 部署会因 `preflight` 检测到「宿主机 nginx 仍在运行 / 证书目录未就绪」而安全退出，**不会改动任何东西**。
- 记下镜像 tag：**这次运行的 commit SHA**（Actions 页面顶部就能看到）。

## 步骤 3：拉镜像（仍不停机）

```bash
cd /opt/work-agent
export IMAGE_TAG=<上一步的 commit SHA>
docker compose -f deploy/docker-compose.prod.yml --env-file .env pull backend frontend

# 如果 Docker Hub 仓库是 private，先登录（必须用 CI 部署所用的同一个用户）
docker login -u <DOCKERHUB_USER>     # 密码填 DOCKER_PAT
```

## 步骤 4：切换（停机窗口开始）

```bash
cd /opt/work-agent
export IMAGE_TAG=<commit SHA>

# 4.1 备份宿主机 Nginx 配置后停用（TLS 移交给 frontend 容器）
sudo cp -a /etc/nginx/conf.d /root/nginx-conf.d.bak-$(date +%F)
sudo systemctl stop nginx
sudo systemctl disable nginx

# 4.2 起容器（此时 frontend 才接管 80/443）
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d

# 4.3 等就绪 + 触发一次完整部署流程（迁移/健康检查/写版本记录）
bash deploy/scripts/deploy.sh
```

> `deploy.sh` 会自动读取上方 `export` 的 `IMAGE_TAG`；若忘记 export，它会在**第一步就报错退出**，不会动任何东西。

## 步骤 5：验证（停机窗口结束）

```bash
# 容器状态：全部 running / healthy
docker compose -f deploy/docker-compose.prod.yml --env-file .env ps

# 公网入口
curl -fsS https://wkcp.online            # 前端页面
curl -fsS https://api.wkcp.online/health # API 存活

# 登录
curl -sX POST https://api.wkcp.online/api/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<admin>","password":"<ADMIN_PASSWORD>"}'

# 端口：只应有 22/80/443（80/443 是 docker-proxy）
sudo ss -ltn
```

## 步骤 6：安装证书续期定时器

```bash
sudo cp /opt/work-agent/deploy/systemd/cert-renew.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cert-renew.timer
systemctl list-timers cert-renew.timer

# 先演练一次（不实际续期）
bash /opt/work-agent/deploy/scripts/renew-cert.sh --dry-run
```

## 步骤 7：清理服务器上的旧源码（达成「服务器只有 Docker」）

```bash
cd /opt/work-agent
ls -a     # 先看一眼，确认要保留的是：.env  deploy/  certbot/
```

```bash
# 保留 .env / deploy/ / certbot/，删除其余（Git 工作区、源码、前端、构建文件）
rm -rf .git .github src frontend docs data logs reports docker \
       .venv node_modules .claude .idea .vscode \
       Dockerfile Dockerfile.frontend .dockerignore .gitignore .gitattributes \
       requirements.txt requirements.prod.txt pyproject.toml uv.lock .python-version \
       CHANGELOG.md AGENTS.md CLAUDE.md README.md .env.ci.example .env.example
```

顺带清掉旧路径下的 Nginx 配置残留（已移到 `conf.d/`，不再被引用）：

```bash
rm -f deploy/nginx/wkcp.online.conf deploy/nginx/api.wkcp.online.conf
ls -R deploy
```

---

# 二、日常发版（全自动）

```
本地 push master
   ↓
Actions: test（全量测试，失败即阻断）
   ↓
Actions: build（构建前后端镜像 → 推 Docker Hub，tag = commit SHA）
   ↓
Actions: deploy
   ├── scp deploy/ → /opt/work-agent/
   └── SSH: bash deploy/scripts/deploy.sh
             └── preflight → 校验 IMAGE_TAG → pull 应用镜像 → up -d
                 → 等 backend 就绪 → 9 个幂等迁移/种子 → 写版本记录 → 健康检查
```

**你只需要 push master。** 服务器上不再有任何构建动作，deploy job 超时也从 30m 降到 10m。

> 手动触发：Actions → CI/CD → Run workflow（`workflow_dispatch`）。

---

# 三、日常操作速查

先注入版本，否则 `docker compose` 会因 `IMAGE_TAG` 未设置直接报错：

```bash
cd /opt/work-agent
export IMAGE_TAG=$(cat deploy/.last_deploy)     # 手动运维命令前必备
```

| 操作 | 命令 |
|------|------|
| 预检 | `bash deploy/scripts/preflight.sh` |
| 更新（等价 deploy.sh） | `IMAGE_TAG=<sha> bash deploy/scripts/update.sh` |
| 回滚上一版本 | `bash deploy/scripts/rollback.sh` |
| 回滚指定版本 | `bash deploy/scripts/rollback.sh <IMAGE_TAG>` |
| 容器状态 | `docker compose -f deploy/docker-compose.prod.yml ps` |
| 后端日志 | `docker logs -f work-agent-backend` |
| Web 入口日志 | `docker logs -f work-agent-frontend` |
| 证书续期演练 | `bash deploy/scripts/renew-cert.sh --dry-run` |
| 立即续期检查 | `bash deploy/scripts/renew-cert.sh` |
| 执行迁移 | `docker compose -f deploy/docker-compose.prod.yml --env-file .env exec backend python -m work_agent.scripts.<脚本>` |
| 查看当前证书 | `docker compose -f deploy/docker-compose.prod.yml --env-file .env --profile certbot run --rm certbot certificates` |

> ⚠️ **不要在生产执行 `docker compose down -v`**：`-v` 会删除数据卷（PostgreSQL / Milvus / MinIO 数据）。
> ⚠️ **不要执行 `docker image prune -a`**：会删掉历史版本镜像，导致回滚时 pull 回旧版本变慢/失败。

---

# 四、回滚

镜像 tag 就是 commit SHA，回滚即「换 tag 重启」：

```bash
bash deploy/scripts/rollback.sh              # 回上一版本（读 deploy/.deploy_history）
bash deploy/scripts/rollback.sh <旧SHA>      # 回指定版本
```

- **不回滚数据库**：迁移（`migrate_*`）不向后执行；若某次发版改坏了 schema，需要人工处理。
- 旧镜像保留在 Docker Hub（历史 tag 不会被覆盖）与服务器本地镜像库里，因此回滚不需要重新构建。

---

# 五、日志管理

- **全部容器**：Docker json-file，`max-size 20m / max-file 5`（compose 已配置）→ `docker logs`
- **Nginx**：容器内 access/error 日志重定向到 stdout/stderr（`deploy/nginx/nginx.conf`），
  统一通过 `docker logs work-agent-frontend` 查看，由 Docker 日志轮转管理
- 宿主机不再有 `/var/log/nginx/`（Nginx 已容器化）
- 无需额外清理；如需长期保留，接入外部日志平台（后续）

---

# 六、网络安全

- 防火墙（ufw）仅开放 **22 / 80 / 443**
- **仅 frontend 容器发布端口**（80/443）；backend 与 PostgreSQL/Milvus/MinIO/Redis **零端口发布**，
  容器之间经 Docker internal 网络用服务名互访（`backend:8000`、`postgres:5432`、`milvus-standalone:19530`）
- 后端不再绑 `127.0.0.1:8000` —— 宿主机上连 8000 端口都不存在了（比 P6-1 更收敛）
- 腾讯云/阿里云安全组与 ufw 双重确认：`sudo ss -ltn` 只应看到 22/80/443
- Docker Hub 凭据只存在于：GitHub Secrets（CI）与服务器 `~/.docker/config.json`（仅当仓库为 private）；
  **绝不写入仓库任何文件**

---

# 七、环境隔离

| | 开发 | 生产 |
|--|------|------|
| compose | `docker-compose.yml`（根目录，**只起依赖**，后端裸跑在 .venv） | `deploy/docker-compose.prod.yml`（全栈容器） |
| .env | 本地（localhost 地址） | 服务器 `.env`（Docker 服务名、强口令、`DOCKERHUB_USER`） |
| 镜像来源 | 本地不需要镜像 | Docker Hub（tag = commit SHA） |
| 前端 | `npm run dev`（:5173） | frontend 容器（Nginx + dist） |
| 初始化 | seed 全量 | 仅 init_db + seed_admin（`deploy.sh` 每次自动跑） |
| 禁止 | — | seed_tenants / seed_knowledge_library / 测试数据 |

---

# 八、CI/CD（GitHub Actions）

- **工作流**：`.github/workflows/ci.yml` —— 3 个 job：
  1. `test`（全分支 + PR，门禁；起 dev compose 的 PG/Milvus/MinIO，跑 `run_all_tests`）
  2. `build`（仅 master push；构建并推送前后端镜像，tag = commit SHA + `latest`；用 GHA 缓存）
  3. `deploy`（仅 master push；`needs: [test, build]` —— 测试或构建失败都不会碰生产；scp 制品 → SSH 执行 deploy.sh）
- **镜像命名**：`<DOCKERHUB_USER>/workagent-backend:<sha>`、`<DOCKERHUB_USER>/workagent-frontend:<sha>`
- **为什么还要 `latest`**：仅为人工排查方便；**生产部署一律用 SHA**（`IMAGE_TAG` 必填），
  不存在「误用 latest 上线」的可能
- **部署制品**：只有 `deploy/` 目录会被 scp 到服务器；`.env` 不在仓库里，永远不会被覆盖

> ⚠️ 测试会消耗真实 DeepSeek token 并有速率限制；`test` job 失败会阻断后续 build/deploy（设计如此）。

---

# 九、企业微信（WeCom）接入

## 1. 企微管理后台配置（用户操作）

1. 企业微信管理后台 → 应用管理 → 自建应用 → 创建「Work Agent」
2. 记录 `AgentId`、`Secret`；「我的企业」→ 企业信息复制 `CorpID`
3. 应用 → 接收消息 → 设置 API 接收：
   - URL：`https://api.wkcp.online/api/wechat/callback`
   - 随机生成 `Token` 与 `EncodingAESKey`（43 字符），加密方式选**安全模式**
   - 保存时企微会立即发送一次 URL 验证请求（GET），成功即通过
4. 应用 → 企业可信IP：加入服务器公网 IP（否则 gettoken / message/send 被拒）

> 域名与回调路径在 P6-2 中**未变**（api.wkcp.online 仍全量反代到 backend），企微后台配置无需改动。

## 2. 服务器 .env 补充变量

```bash
WECHAT_CORP_ID=wwxxxxxxxxxxxxxxxxxx
WECHAT_SECRET=<Secret>
WECHAT_TOKEN=<Token>
WECHAT_AGENT_ID=<AgentId>
WECHAT_ENCODING_AES_KEY=<EncodingAESKey 43字符>
WECHAT_AUTO_CREATE_USER=false
WECHAT_DEFAULT_TENANT_ID=
```

## 3. 验证

```bash
# URL 验证：无 msg_signature（明文模式）会原样回显 echostr，便于确认路由可达
curl -fsS "https://api.wkcp.online/api/wechat/callback?echostr=test"
# 后端日志：员工发消息后应看到请求进入
docker logs -f work-agent-backend
```

## 4. 用户绑定

- 登录 `https://wkcp.online` → 菜单「用户绑定」：给员工填写企微 `userid` 完成绑定（`user:manage` 权限，SUPER_ADMIN / TENANT_ADMIN）
- 或 API：
  - `PUT /api/admin/users/{id}/wechat` body `{"wechat_user_id": "zhangsan"}`
  - `DELETE /api/admin/users/{id}/wechat` 解绑
- 未绑定员工提问 → 收到「请联系管理员绑定」提示；`WECHAT_AUTO_CREATE_USER=true` 时首次消息自动建号（需配置 `WECHAT_DEFAULT_TENANT_ID`）

---

# 十、故障排查

| 现象 | 原因 / 处理 |
|------|-------------|
| `docker compose` 报 `IMAGE_TAG` 未设置 | 预期行为（防止误用 latest）。`export IMAGE_TAG=$(cat deploy/.last_deploy)` 后重试 |
| frontend 容器反复重启 / `nginx: [emerg] cannot load certificate` | 证书卷缺失或符号链接断链。检查 `/opt/work-agent/certbot/conf/live/wkcp.online/fullchain.pem` 是否可读；`docker logs work-agent-frontend` |
| preflight 报「宿主机 nginx 仍在运行」 | 归一化切换未完成：`sudo systemctl stop nginx && sudo systemctl disable nginx` |
| preflight 报缺少证书 | 步骤 1.1 未做完（`cp -a /etc/letsencrypt/.` ） |
| `pull` 报 `unauthorized` | Docker Hub 仓库为 private 且服务器未登录：`docker login -u <user>`（密码用 PAT），**必须是跑 deploy.sh 的同一个用户** |
| 大文件上传 413 | Nginx 上限（当前 `client_max_body_size 50m`，在 `deploy/nginx/nginx.conf`）。**配置在镜像里 → 改完必须发版**（push master）才生效 |
| 证书续期失败 | `bash deploy/scripts/renew-cert.sh --dry-run` 看报错；`systemctl status cert-renew`；确认 80 端口可达（ACME webroot 校验走 80） |
| 部署后站点仍显示旧前端 | 浏览器缓存（`/assets/` 有 7 天 immutable 缓存）或 CDN；确认 `deploy/.last_deploy` 的 SHA 与 Actions 一致 |

---

# 十一、登录服务器后要执行的命令清单（速查）

```bash
# —— 首次上线：见本文件第一章（1→7 步）——

# —— 日常 ——
cd /opt/work-agent
export IMAGE_TAG=$(cat deploy/.last_deploy)
docker compose -f deploy/docker-compose.prod.yml --env-file .env ps
docker logs -f work-agent-backend
bash deploy/scripts/preflight.sh
bash deploy/scripts/rollback.sh

# —— 发版 ——
# 本地 push master 即可（Actions 自动 test → build → deploy）
```
