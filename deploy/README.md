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

## ⚠️ 部署前必读（阻塞项）

**Milvus 连接地址接线**：`rag/milvus_store.py` 目前硬编码 `uri="http://localhost:19530"`，容器内无法连到 Milvus。生产部署**必须先**将该处改为读取 `settings.milvus_uri`（配置字段已加，`MILVUS_URI=http://milvus-standalone:19530`）。此为唯一必要的业务接线改动（不改 RAG 逻辑），需在部署前完成并获确认。

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
