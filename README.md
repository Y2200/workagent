# Work Agent

企业内部智能督导 Agent + 企业知识库管理系统。

员工在企业微信提问制度知识 / 收发任务，由 LLM Agent 结合企业知识库与 RBAC 权限给出回答；管理员通过 Web 后台上传文档、查看审计、运营治理。

## 功能特性

- **企业微信问答**：企微消息 → 身份解析 → Agent Runtime → RAG 检索知识库 → 回答；支持文字与**语音**（企微云端 `Recognition` 直取，阿里云 ASR 兜底）
- **企业知识库**：PDF / Word / Markdown / TXT 上传 → 解析 → 切分 → Embedding → Milvus；按部门 / 角色 / 用户做文档级权限控制
- **任务督导**：任务发布（多轮确认）→ 查询 / 提交 / 审核 / 完成；自动督办（每日扫描逾期风险 → 企微提醒员工）；统计看板 + Excel/Word 导出 + 周报邮件
- **企业 Agent 平台**：Intent Router → Planner → Multi-Agent（Knowledge / Operation / Analysis / Task）→ Tool 调用 → Audit 审计全链路
- **生产治理**：链路追踪（Trace）、配置中心、Prompt 治理、LLM 成本预算、故障恢复（重试 / 熔断 / 确定性回退）、健康监控
- **权限与审计**：RBAC 四角色 + 权限码；`agent_logs` / `operation_logs` 全量审计；操作日志、归档、统计

## 架构

```
企业微信 ─┐                ┌─ FastAPI ── Service 层 ── Repository 层 ──┬─ PostgreSQL（业务数据 / 审计）
Web 后台 ─┴─ 请求 ──→ API ─┤                                          ├─ Milvus（向量检索 / 知识库）
                            │                                          ├─ MinIO（文档对象存储）
                            └─ Agent Runtime ──┐                       └─ Redis（缓存 / 去重）
                                Intent Router  │
                                Planner        ├── RAG Agent / Task Agent / Analysis Agent
                                Supervisor     │        （经 Tool → Service，不直连 DB）
                                Audit / Trace ─┘
```

分层铁律：`API → Service → Repository → DB`；Agent 只经 `Router → Tool → Service`；业务 Prompt 全部外置到 `src/work_agent/prompts/`。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · uvicorn |
| Agent | LangChain / LangGraph · DeepSeek（OpenAI 兼容协议） |
| 前端 | Vue 3 · Vite · Element Plus |
| 数据库 | PostgreSQL 16（SQLAlchemy 2.0）· Milvus 2.5（bge-small-zh 向量） |
| 存储 / 缓存 | MinIO · Redis |
| 接入 | 企业微信自建应用（消息回调 + 主动推送） |
| CI/CD | GitHub Actions（测试门禁 + SSH 自动部署） |

## 快速开始（本地开发）

```bash
# 1. 配置
cp .env.example .env          # 填入企微 / LLM / 数据库等真实值

# 2. 启动依赖容器（PostgreSQL / Milvus / MinIO）
docker compose up -d

# 3. 建表 + 初始化（管理员 / 租户 / RBAC / 种子知识库，均为幂等）
python -m work_agent.scripts.init_db
python -m work_agent.scripts.seed_admin
python -m work_agent.scripts.seed_rbac
python -m work_agent.scripts.seed_knowledge_library --reset

# 4. 后端（src-layout，需 PYTHONPATH=src）
python -m uvicorn work_agent.main:app --host 127.0.0.1 --port 8000

# 5. 前端（:5173，/api 代理到 :8000）
cd frontend && npm install && npm run dev
```

完整命令清单（迁移 / 种子 / 单套件测试）见 `docs/project-context.md`（本地开发文档）。

## 测试

```bash
python -m work_agent.scripts.run_all_tests        # 一键全量回归（本地需依赖容器）
python -m work_agent.scripts.test_<name>          # 单个测试套件
python -m work_agent.scripts.run_agent_evaluation # Agent 评测（50 案例）
```

CI 已配置 `.github/workflows/ci.yml`：push 任意分支跑全量测试门禁，push `master` 通过后 SSH 自动部署生产。

## 目录结构

```
src/work_agent/
├── api/            # FastAPI 路由（admin / wechat / health / traces / configs / ...）
├── agent/          # Agent 层（Runtime / IntentRouter / Planner / Supervisor / Tools / Loop / Evaluation）
├── rag/            # RAG（Milvus 检索 / 权限过滤 / 评测）
├── wechat/         # 企业微信接入（回调加解密 / 解析 / 推送 / 语音识别）
├── services/       # Service 层（文档 / 任务 / 审计 / 成本 / 健康 / 提醒 / 周报）
├── repositories/   # Repository 层
├── db/models/      # SQLAlchemy 模型
├── document/       # 上传管线（解析 → 切分 → Embedding → Milvus）
├── knowledge/      # 知识智能（分类 / 图谱 / 相似 / 质量）
├── prompts/        # 业务 Prompt 模板（外置，经 PromptManager 加载）
├── scheduler/      # 定时任务（APScheduler：督办 / 周报）
└── scripts/        # 初始化 / 迁移 / 种子 / 测试脚本
frontend/           # Vue 3 管理后台
deploy/             # 生产部署体系（compose / nginx / scripts，详见 deploy/README.md）
docs/               # 架构审查等文档
```

## 文档

- `docs/project-context.md` — 项目活文档（目标 / 架构 / 已完成阶段 / 下一步）
- `docs/architecture-review.md` — 架构审查结果
- `deploy/README.md` — 生产部署手册（腾讯云 / 阿里云）

## 安全

- 真实密钥只存在于服务器 `.env`，已 gitignore；仓库仅提交占位符模板 `.env.example`
- 多租户隔离：所有数据查询按 `tenant_id` 过滤；Agent 执行经 RBAC + 审计
