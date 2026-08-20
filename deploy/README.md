# P6-1 生产部署手册

企业级部署体系（腾讯云 Ubuntu + 域名 `wkcp.online`）。**本文件为服务器执行步骤，不含任何凭据。**

```
Internet → Nginx(宿主机, Certbot TLS)
  ├── https://wkcp.online      → frontend/dist + /api/* → 127.0.0.1:8000
  └── https://api.wkcp.online  → FastAPI（API 直连）
        ↓ Docker（deploy/docker-compose.prod.yml，内部网络）
  backend / postgres / milvus / work-minio / redis（DB/Milvus/MinIO/Redis 不发布任何公网端口）
```

---

## ⚠️ 部署前必读

`rag/milvus_store.py` 已读取 `settings.milvus_uri`（生产 `.env` 配 `MILVUS_URI=http://milvus-standalone:19530`，容器内可达 Milvus）。此接线已完成，无需改动。

---

## 一、腾讯云 Ubuntu 首次部署手册

### 1. SSH 登录
```bash
ssh ubuntu@<腾讯云公网IP>
# 或 ssh root@<公网IP>
```

### 2. 上传代码
```bash
# 在本地开发机将代码推送到 Git 仓库后，在服务器克隆
git clone <你的私有仓库地址> /opt/work-agent
cd /opt/work-agent
```
> 若用 rsync/scp 上传：只上传源代码与部署文件，**绝不上传 `.env`**。

### 3. 服务器初始化（docker / nginx / certbot / ufw，防火墙仅 22/80/443）
```bash
cd /opt/work-agent
sudo bash deploy/scripts/init-server.sh
# 重新登录使 docker 组生效
exit && ssh ubuntu@<公网IP>
```

### 4. 创建生产 .env
```bash
cd /opt/work-agent
cp .env.example .env
chmod 600 .env
# 用编辑器填写全部真实值（生产用 Docker 内部服务名）：
#   DATABASE_URL=postgresql+psycopg2://postgres:<POSTGRES_PASSWORD>@postgres:5432/work_agent
#   MILVUS_URI=http://milvus-standalone:19530
#   MINIO_ENDPOINT=work-minio:9000
#   REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0
#   CORS_ORIGINS=https://wkcp.online
#   JWT_SECRET / ADMIN_PASSWORD / DOUBAO_API_KEY 等
```
强随机口令生成：
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. 部署（构建后端镜像 + 启动全部服务 + 配置 Nginx）
```bash
bash deploy/scripts/deploy.sh
```

### 6. HTTPS 证书（Let's Encrypt）
```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d wkcp.online -d api.wkcp.online
# 自动续期：certbot 已安装 systemd timer，无需手动
sudo certbot renew --dry-run
```

### 7. 首次初始化数据库与管理员（仅执行一次）
```bash
bash deploy/scripts/init-prod.sh
# 仅执行 init_db + seed_admin；绝不含测试数据
```

### 8. 健康检查
```bash
docker compose -f deploy/docker-compose.prod.yml --env-file .env ps   # 全部 healthy
curl -fsS http://127.0.0.1:8000/health                                # 后端存活
curl -fsS https://wkcp.online                                         # 前端
curl -fsS https://api.wkcp.online/health                              # API 存活
# 登录验证
curl -sX POST https://api.wkcp.online/api/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"<admin>\",\"password\":\"<ADMIN_PASSWORD>\"}"
```

---

## 二、日常操作

| 操作 | 命令 |
|------|------|
| 预检 | `bash deploy/scripts/preflight.sh` |
| 更新 | `bash deploy/scripts/update.sh [branch]` |
| 回滚 | `bash deploy/scripts/rollback.sh`（回到 deploy/.last_deploy） |
| 容器状态 | `docker compose -f deploy/docker-compose.prod.yml ps` |
| 后端日志 | `docker logs -f work-agent-backend` |
| 迁移 | `docker compose -f deploy/docker-compose.prod.yml exec backend python -m work_agent.scripts.<迁移脚本>` |
| 证书续期 | 自动（systemd timer）；手动 `sudo certbot renew` |

---

## 三、日志管理

- **后端/依赖**：Docker json-file，`max-size 20m / max-file 5`（compose 已配置），日志 `docker logs` 查看
- **Nginx**：`/var/log/nginx/`（access/error），由系统 logrotate 轮转
- 无需额外清理；如需更长期保留，接入外部日志平台（后续）

---

## 四、网络安全

- 防火墙（ufw）仅开放 **22 / 80 / 443**
- 数据库/Milvus/MinIO/Redis **不发布任何端口**（仅 Docker 内部网络）
- 后端仅绑定 `127.0.0.1:8000`（仅本机 Nginx 可达）
- 腾讯云安全组与 ufw 双重确认：`ss -ltn` 只应看到 22/80/443（+本机回环 8000）

---

## 五、环境隔离

| | 开发 | 生产 |
|--|------|------|
| compose | `docker-compose.yml` | `deploy/docker-compose.prod.yml` |
| .env | 本地（localhost） | 服务器 `.env`（内部服务名、强口令） |
| 初始化 | seed 全量 | 仅 init_db + seed_admin |
| 禁止 | — | seed_tenants / seed_knowledge_library / 测试数据 |

---

## 六、登录腾讯云后要执行的命令清单（速查）

```bash
# 1. 克隆代码
git clone <仓库> /opt/work-agent && cd /opt/work-agent
# 2. 初始化服务器
sudo bash deploy/scripts/init-server.sh && exit   # 重新登录
# 3. 创建 .env
cp .env.example .env && chmod 600 .env            # 填真实值（见上文第4步）
# 4. 部署
bash deploy/scripts/deploy.sh
# 5. HTTPS
sudo certbot --nginx -d wkcp.online -d api.wkcp.online
# 6. 首次初始化
bash deploy/scripts/init-prod.sh
# 7. 验证
docker compose -f deploy/docker-compose.prod.yml ps
curl -fsS https://wkcp.online && curl -fsS https://api.wkcp.online/health
```

---

## 七、企业微信（WeCom）接入

### 1. 企微管理后台配置（用户操作）

1. 企业微信管理后台 → 应用管理 → 自建应用 → 创建「Work Agent」
2. 记录 `AgentId`、`Secret`；「我的企业」→ 企业信息复制 `CorpID`
3. 应用 → 接收消息 → 设置 API 接收：
   - URL：`https://api.wkcp.online/api/wechat/callback`
   - 随机生成 `Token` 与 `EncodingAESKey`（43 字符），加密方式选**安全模式**
   - 保存时企微会立即发送一次 URL 验证请求（GET），成功即通过
4. 应用 → 企业可信IP：加入服务器公网 IP（否则 gettoken / message/send 被拒）

### 2. 服务器 .env 补充变量

```bash
WECHAT_CORP_ID=wwxxxxxxxxxxxxxxxxxx
WECHAT_SECRET=<Secret>
WECHAT_TOKEN=<Token>
WECHAT_AGENT_ID=<AgentId>
WECHAT_ENCODING_AES_KEY=<EncodingAESKey 43字符>
WECHAT_AUTO_CREATE_USER=false
WECHAT_DEFAULT_TENANT_ID=
```

### 3. 部署

```bash
cd /opt/work-agent
git pull
# 注册 user:manage 权限（幂等，可重复执行）
docker compose -f deploy/docker-compose.prod.yml --env-file .env exec backend \
  python -m work_agent.scripts.seed_rbac
bash deploy/scripts/deploy.sh
```

### 4. 验证

```bash
# URL 验证：无 msg_signature（明文模式）会原样回显 echostr，便于确认路由可达
curl -fsS "https://api.wkcp.online/api/wechat/callback?echostr=test"
# 后端日志：员工发消息后应看到请求进入
docker logs -f work-agent-backend
```

### 5. 用户绑定

- 登录 `https://wkcp.online` → 菜单「用户绑定」：给员工填写企微 `userid` 完成绑定（`user:manage` 权限，SUPER_ADMIN / TENANT_ADMIN）
- 或 API：
  - `PUT /api/admin/users/{id}/wechat` body `{"wechat_user_id": "zhangsan"}`
  - `DELETE /api/admin/users/{id}/wechat` 解绑
- 未绑定员工提问 → 收到「请联系管理员绑定」提示；`WECHAT_AUTO_CREATE_USER=true` 时首次消息自动建号（需配置 `WECHAT_DEFAULT_TENANT_ID`）

---

## 八、CI/CD 自动化部署（GitHub Actions）

> 触发链路：`commit → push master → Actions: 全量测试 → SSH 服务器 → git pull → docker build backend → 启新容器 → 幂等迁移 → 重建前端 → 上线`。PR 只跑测试（门禁），master push 才部署。**无镜像仓库，服务器本地构建（方案A）。**

### 1. 工作流文件

- `.github/workflows/ci.yml` —— 2 个 job：`test`（全量测试，全分支+PR）/ `deploy`（SSH，仅 master）
- 测试 runner：`python -m work_agent.scripts.run_all_tests`（逐个跑 45 个脚本式测试，汇总 `ci-reports/ci_test_results.json`）
- 部署脚本：`deploy/scripts/deploy.sh master`（服务器：git pull → docker build backend → up -d → 9 项幂等迁移 → 前端 npm build → nginx reload → 记录回滚点）

### 2. 首次启用需配置（用户操作，敏感值不进仓库）

**a. 服务器 SSH**
- 生成一对专用部署密钥，公钥加入服务器 `~/.ssh/authorized_keys`，私钥完整内容存为 GitHub Secret `DEPLOY_SSH_KEY`
- 建议服务器安全组对 GitHub Actions 出口 IP 段放行 22 端口

**b. GitHub 仓库 Secrets（`Y2200/workagent` → Settings → Secrets and variables → Actions）**

| Secret | 值 |
|--------|-----|
| `DEPLOY_HOST` | 服务器 IP/域名 |
| `DEPLOY_USER` | 服务器 SSH 用户，如 `ubuntu` |
| `DEPLOY_SSH_KEY` | 部署用 SSH 私钥（完整 `-----BEGIN ... PRIVATE KEY-----` 块） |
| `LLM_API_KEY` | DeepSeek API key（CI 测试真实 LLM 用例） |

服务器 `.env` **无需任何额外变量**（方案A：compose 在服务器本地构建，不引用镜像名）。

### 3. 日常

- **发版**：push 到 `master`，观察 Actions 两个 job 依次通过；失败在该 job 标红。
- **回滚**：`bash deploy/scripts/rollback.sh`（回 `deploy/.last_deploy` 记录的 commit，服务器本地重建）。
- **手动触发部署**：Actions → CI/CD → Run workflow（`workflow_dispatch`）。
- **迁移自动执行**：`deploy.sh` 每次部署自动跑全部幂等迁移/种子（init_db/seed_admin/各 migrate_*/seed_rbac），不再需要手工 `seed_rbac`。

> ⚠️ 测试会消耗真实 DeepSeek token 并有速率限制；`test` job 失败会阻断部署（设计如此）。如需跳过 LLM 用例可另行调整。
