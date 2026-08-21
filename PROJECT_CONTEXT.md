# Work Agent 项目上下文

> 本文档用于项目开发上下文迁移。
> 新对话开始时，将此文件提供给 AI，使其快速了解项目目标、当前架构、已完成模块和下一步开发计划。


---

# ⚡ 当前状态（2026-08-21，GitHub Actions CI/CD 45/45 冲刺中）

**代码状态**：本地 `master` = `63a5ae0`，工作区干净（仅 AGENTS.md 未跟踪未定论），全部已推送。生产已上线：`https://wkcp.online`（前端）、`https://api.wkcp.online`（API）。

## 最新（2026-08-20→21）：GitHub Actions CI/CD 流水线（方案A：服务器本地构建，无镜像仓库）

- **流水线**：`.github/workflows/ci.yml` —— 2 job：`test`（全分支+PR 门禁，起 dev compose 的 PG/Milvus/MinIO）→ `deploy`（仅 master push，SSH 服务器跑 `deploy/scripts/deploy.sh master`）
- **测试 runner**：`scripts/run_all_tests.py` —— 子进程逐个跑 45 个脚本式测试 + JSON 汇总到 `ci-reports/` + 失败非零退出；参数 `--only/--skip/--no-setup/--timeout`；**预测试初始化**（init_db/seed_admin/seed_tenants/seed_rbac/seed_knowledge_library/各 migrate_*，均幂等，CI 空库与本地库都适用）
- **deploy.sh 增强**：默认分支 main→master；新增「5.5 幂等迁移块」（等 backend 就绪后跑 init_db/seed_admin/各 migrate_*/seed_rbac，每次部署自动执行，不再手工 seed_rbac）
- **CI env 关键值**：`PYTHONPATH=src`（src-layout）；DATABASE_URL/MILVUS_URI/MINIO 指向 localhost（dev compose 凭据 minioadmin）；`DOUBAO_API_KEY`=Secret `LLM_API_KEY`；`JWT_SECRET`（非空）/`ADMIN_USERNAME=admin`/`ADMIN_PASSWORD=admin123`；`TENANT_ID=1`
- **GitHub Secrets（4 个，用户已配）**：`DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY`/`LLM_API_KEY`（详见 deploy/README.md 第八节）
- **本地 git 环境**：SSH remote 切回 HTTPS→已改回 SSH（个人密钥 `~/.ssh/id_ed25519_github` 注册 GitHub，`~/.ssh/config` 指向它；部署密钥 `id_ed25519`(github-actions) 仅用于服务器，两者分离）
- **修复的 CI 适配问题**（逐条详见 errors.txt 2026-08-21 四条记录）：空库 UndefinedTable→runner 预建 schema；conversation_message 模型重复索引→移除列级 index=True；JWT 空 key→CI env 补 JWT_SECRET；prompt 版本 1.0→1.1 与评测分布断言过时；`search_with_meta` denied 语义 `len(results)==0`→`<len(candidates)`（对齐 docstring）；seed 文档 roles 去通用"员工"（财务报销/采购审批，部门隔离）；seed_admin 平台管理员固定租户 `""`（避免 TENANT_ID 破坏默认租户可见审计）
- **测试进度**：6/45 → 21/45 → 38/45 → 43/45 → 最后 2 个（test_operation_audit/test_audit_intelligence，seed_admin 租户问题）已修，**等待 45/45 全绿确认**
- **验证**：若 test 全绿 → deploy job SSH 上服务器执行 `deploy.sh master`（git pull → docker build → 幂等迁移 → 前端 → nginx）→ 生产自动上线

## 最新（2026-08-16→17）：企业任务型 Agent 升级（6-4.txt 路线 Phase 7A-12）
- **核心原则**：不是通用聊天 Agent，而是**企业任务执行 Agent**（Manager/Employee/System 三角色）
- **Phase 7A 企业任务决策层**：`agent/policy.py`（意图级前置 RBAC，双保险）+ RBAC +7 权限码（task:submit/view_employee/remind/email:send/policy:view/system:scan/report:send）+ 8 任务意图拆分（query_my/query_employee/create/submit/remind/summary/policy_query/unknown）+ Planner 结构化 command + summary
- **Phase 8 Task Command Validator**：`agent/tools/validator.py`（Schema 结构校验拒绝自由文本 + 业务规则：执行人存在/同部门/deadline/查重）
- **Phase 9 Task Lifecycle**：`agent/task_flow.py` 状态机（CREATED→ASSIGNED→IN_PROGRESS→SUBMITTED→REVIEWED→COMPLETED，任何阶段 CANCELLED；映射现有字段）+ task_service.transition
- **Phase 10 Enterprise Knowledge**：`agent/organization.py` 权限类问题（"我能不能申请远程办公"）结合用户画像（角色/部门/权限）回答
- **Phase 11 System Proactive Agent**：`agent/system_agent.py`（is_system + Policy system 权限校验，scheduler 接入）
- **Phase 12 Evaluation 增强**：agent_cases.json +5 任务 case（55 条）；顺带修复 intent_router fallback 歧义 + cost_governance 时区 bug
- **验证**：生产套件 6/6+契约；评测 55 条通过 52（intent 0.9167/安全/隔离/回归 1.0）；新增测试 test_policy/test_validator/test_task_flow/test_knowledge_enterprise/test_system_agent

**Memory 边界冻结（2026-08-16 用户确认）**：Work-Agent 不是陪聊机器人，Memory 只负责"保证当前任务连续理解"，不保存用户一切历史。**冻结范围**：
- ✅ 做：conversation_id（会话身份）、conversation_messages（完整历史，不删）、最近 6 轮 Context Window（转 BaseMessage 进 AgentContext.chat_history）、Query Rewrite（history 只用于改写，不 embedding）
- ❌ 不做：>6 轮长期记忆、用户习惯记忆、通用长期记忆管理器、Summary Memory、自动记忆提取
- ⚠️ 企业事实（员工/部门/职责）不写入 Memory，由 RAG/DB 负责（事实会变，存 Memory 造成数据冲突）
- 规则：后续新增 Memory 能力必须重新评估价值与复杂度

## 最新（2026-08-16）：轻量统一 State + RAG 会话记忆（6-3.txt 调整版）
- **目标**：补上 Agent 连续上下文（conversations 表原只有 message_count 零历史；"那经理呢？"追问无法工作）
- **不做 LangGraph 重构**：保持现有 runtime 主链路，不引入 langgraph-checkpoint-postgres，不改主流程
- **Phase 1 会话存储**：conversation_messages 表（role user/assistant/tool/system + scope + tool_name + extra）+ conversation_memory_service（adapter 转 BaseMessage）+ runtime 统一加载/写历史
- **Phase 2 RAG rewrite**：agent/query_rewriter（_is_follow_up 指代词优先）+ conversation_rewrite prompt + KnowledgeAgent 接入，"那经理呢？"能改写检索
- **Phase 3 统一上下文**：AgentContext.chat_history 共享；preview_create_task 读历史辅助理解，业务决策隔离（执行人/日期确定性）
- **Phase 4 生产优化**：context window（不删历史）+ 异常容错 + 跨用户隔离 + scope 字段；task_pending_creates 改 partial unique index（允许多条历史）
- **测试**：test_rag_memory（Part A-D）

**代码状态**：本地 `master` = `70bc1f1`（Enterprise Agent Phase 1-4）。生产已上线：`https://wkcp.online`（前端）、`https://api.wkcp.online`（API）。

## 最新（2026-08-16）：升级为企业智能任务 Agent（4 Phase 完成）
- **目标**：从"提问→LLM→查库→回答"升级为"企业 Agent 工具编排层"（非聊天机器人），任务 Agent 为核心
- **Phase 1 基础能力**：BaseTool 统一权限钩子、AgentContext.role_codes、ToolRegistry 含权限信息、TaskTool schema 修复
- **Phase 2 任务查询**：task_tool.department_tasks（按部门查任务）、user_tool（解析员工/部门成员）、check_department_scope、UserService（Tool 经 Service 禁直连 DB）
- **Phase 3 任务创建**：task_pending_creates 表 + preview/confirm/cancel create（企微多轮确认）；执行人 DB 确定性、日期代码规则、LLM 仅补描述；TASK_CREATE 意图
- **Phase 4 通知+督办**：notification_tool（企微/邮件提醒，send_email 确认+SMTP 检查）、主动督办增强（staleness/部门 digest）、周报部门经理投递、agent_logs.confirmed 审计字段、task:notify 权限码
- **测试**：test_enterprise_agent（Part A-F 12 项）+ test_task_reminder_extended（5 项）+ 全量回归绿

**代码状态**：本地 `master` = `a6eb3ed`（一致性修复）+ 租户语义修复（待提交）。生产已上线：`https://wkcp.online`（前端）、`https://api.wkcp.online`（API）。

## 最新（2026-08-16）：企微查不到 Web 空租户文档 → 已修复
- **bug**：企微提问回复"未检索到相关制度"，Web 端能搜到同一批文档
- **根因**：Web 管理员（tenant_id=""）上传的文档空租户；企微用户绑定租户1；检索 filter `metadata["tenant_id"]=="1"` 精确过滤 → 企微用户只命中租户1文档，Web 空租户文档全被挡。单企业一套知识库，可见性应由文档级权限（visibility/access）控制，非租户
- **修复**：`core/utils.py` 新增 `build_tenant_filter()`（空租户文档全局可见 + 自己租户）；`rag/service.py`（企微 Agent 入口）+ `knowledge/service.py`（Web 入口）接入
- **测试**：`scripts/test_tenant_global_docs.py` 4 部分 + 回归全绿（生产套件 6/6+契约）

## 最新（2026-08-16）：删除-管线竞态修复（文档孤儿向量）
- **bug**：Web 上传后立即删除文档 → Milvus 孤儿向量（PG 已删、向量残留），删除后新导入的文档被孤儿污染/挤出搜索（"中间删除后新导入查不到"）
- **根因**：upload 建记录后异步管线线程池执行；删除若在管线插入 Milvus 前完成，delete 时 knowledge_chunks 为空 → 删不到"还没插入的向量" → 管线随后插入 → 孤儿
- **修复**：① delete() 先置 status=deleting 通知管线；② 管线插入 Milvus 前 `_is_active` 校验（被删跳过插入）；③ 插入后落库前二次校验（被删则 `delete_by_document` 回滚自愈）；文件 `services/document_service.py` + `document/pipeline.py`
- **测试**：`scripts/test_document_consistency.py` 3 部分（顺序删除彻底/删除后新导入可检索/竞态最终 0 孤儿）+ 全量回归绿（生产套件 6/6+契约）
- **经验**：异步管线与删除必须互斥；删除先发"停止信号"再清理，管线插入前后各校验一次

## 已上线（生产服务器已部署）
- 企微接入：回调 `api/wechat.py` + 手写 WXBizMsgCrypt（`wechat/crypto.py`）+ 统一 WeComClient（Redis token 缓存）+ 用户绑定 `api/users.py`/`Users.vue`
- Milvus 租户元数据修复（`repair_milvus_metadata.py` + `update_document_metadata`）
- 任务督导 MVP + 二轮优化（见下）

## 最近完成（已推送 `87edaa4`，服务器部署验证中）
- 任务督导 Phase 4：统计/周报/邮件（见下「任务统计 / 周报 / 邮件」）
- 用户管理增强 A/B/C（见下）
- 企微链路排障：闲聊路由 + 督导 JSON 容错（"你好"不再"系统繁忙"）
- 邮件基础设施：SMTP + `User.email` + 任务完成邮件 + 每周周报（`EMAIL_ENABLED` 默认关）

## ⏳ 唤醒后优先（2026-08-17 存进度）
1. **服务器部署验证（6-4 企业任务型 Agent）**：`git pull` → `docker compose -f deploy/docker-compose.prod.yml --env-file .env exec backend python -m work_agent.scripts.seed_rbac`（+7 权限码）→ `up -d --build backend`
2. 验证三角色权限：员工发"给张三安排任务"→拒绝；经理发同消息→确认流；员工"我能不能申请远程办公"→结合角色回答；定时任务（TASK_REMINDER_ENABLED=true）→ System Agent 扫描提醒
3. 后续方向（未做）：前端治理看板接入（P5-5 traces/configs/prompts/cost/resilience/health）、Celery 异步管线、技术债务（get_llm 缓存/废弃 server.py）、多部门隔离 department_id 外键落地

## 任务督导（已完成，全量回归绿）
- **模型**：`tasks`/`task_updates`/`task_pending_updates`/`task_notifications` 四表（`db/models/task.py` + `scripts/migrate_tasks.py`）
- **服务**：`task_service` + `task_repository` + `notification_service`（创建/查询/提交/确认/取消/批量/通知）
- **Agent**：`task_agent` + `task_tool`（list/detail/submit/submit_all/confirm/cancel/complete）；新意图 `task_management`
- **AI 确认机制**：提交 → AI 解析 → 写 pending（不落正式表）→「确认提交吗？」→ 回「确认」→ 落 task_updates + 更新 progress
- **二轮优化**：①任务上下文路由（短任务名→detail，embedding 相似，不用 contains）②提交解析优化（提交≠summary）③批量提交 submit_all ④Web 发布企微提醒 `send_task_created`（失败不影响建任务）⑤task_notifications 通知记录表
- **Web**：`api/tasks.py` + `Tasks.vue`；权限 `task:view/create/manage`（seed_rbac）
- **多租户原则**：task.tenant_id 归属负责人 employee；SUPER_ADMIN 全量/租户管理员隔离
- 测试：`scripts/test_task_agent.py` 11 部分；生产套件 6/6+契约
- **Phase 3 自动督办（已完成）**：`scheduler/task_scheduler.py`（APScheduler 每日 CronTrigger，main.py lifespan 启停）+ `services/task_reminder_service.py`（确定性风险判断：逾期/剩余天数+进度+优先级 → high/medium/low；模板文案；`scan_and_remind` 企微提醒员工，未绑定记 failed 不阻塞）+ `task_repository.list_remindable`（平台扫描未完成含截止任务）；配置 `TASK_REMINDER_ENABLED/TIME/MIN_RISK`；测试 `scripts/test_task_reminder.py` 7 部分；依赖 `apscheduler>=3.10,<4`

## 用户管理增强（A/B/C 已完成，待部署）
- **Web 新建/编辑用户**：`POST /api/admin/users` + `PUT /api/admin/users/{id}`（`user:manage`；SUPER_ADMIN 全量/租户管理员本租户且不能越权提权；username/wechat 唯一 409、短密码 400、有任务禁改租户 409）；前端 Users.vue 新建/编辑按钮 + real_name 列 + 角色下拉按权限过滤
- **real_name 显示名字段**：`users.real_name`（可重复，`username` 仍唯一登录名）；企微自动建号取企微 `name`；迁移 `scripts/migrate_user_profile.py` 幂等回填=username
- **企微绑定并发加固**：`users.wechat_user_id` 部分唯一索引（1 企微号 ↔ 1 用户）+ `_auto_create_user` find-or-create（IntegrityError→回滚→返回已存在者，并发/重试不报错不重复）
- **`/auth/me` 加 roles**：前端按权限过滤角色下拉
- 测试：`scripts/test_user_management.py` 8 部分；回归 test_rbac / test_task_agent / 生产套件全绿；前端 build 通过

## 企微链路排障（闲聊路由 + 督导 JSON 容错，已完成）
- 现象：企微回复"系统繁忙"；`supervision_action.py:67` json.loads 崩（DeepSeek 对问候返回空/散文）
- 修复：`core/utils` 加 `safe_parse_json`（剥围栏/平衡提取首个{} / default 兜底）+ `is_greeting`；`supervision_action`/`task_supervision` 改用容错解析 + 失败日志；planner 把 `SMALL_TALK`/问候 → `kind=chat`，supervisor 直接友好回复（问候不再进旧督导流）
- 测试：`test_chat_routing.py` 5/5；回归 `test_task_agent` / `test_user_management` / 生产套件全绿

## 任务统计 / 周报 / 邮件（Phase 4，已完成）
- **统计 API**：`GET /api/admin/task/stats`（overview/按部门/按员工/完成率/风险计数，风险复用 Phase3 确定性 `compute_risk`）+ 导出 `GET /api/admin/task/stats/export?format=xlsx|docx`（`task:manage` + 租户隔离）
- **导出**：openpyxl 生成 xlsx + python-docx 生成 docx（`StreamingResponse` 首个文件下载）；**requirements.prod.txt 手工追加 openpyxl/et-xmlfile（未用 uv export）**
- **周报**：`GET /api/admin/task/report/weekly`（JSON）+ `/weekly/export?format=docx`（Word 下载）；`task_report_service` 近 7 天完成/延期/高风险 + 确定性建议；APScheduler 每周定时生成 + 邮件发送 `WEEKLY_REPORT_EMAILS`
- **邮件**：`email_service`（SMTP SSL/STARTTLS，默认关 EMAIL_ENABLED=false）；任务完成 → `send_task_completed_email`（收件人=创建者/主管）；`User.email` 字段 + 迁移；用户管理页加邮箱
- **前端**：`TaskStats.vue` 任务统计页（overview 卡/部门/员工/风险表 + 导出/周报按钮 blob 下载）+ 路由/菜单
- 测试：`scripts/test_task_stats.py` 6 部分；回归 test_task_agent 11/11、test_user_management 8/8、生产套件 6/6+契约、前端 build

## 下一步
1. **CI/CD 全绿确认**：等待最新 push（`63a5ae0`）的 Actions `test` job 45/45 通过
2. **若 test 全绿** → `deploy` job 自动 SSH 上服务器跑 `deploy.sh master`（git pull → docker build → 幂等迁移 → 前端 → nginx）→ 验证生产：`curl https://api.wkcp.online/health`、三角色权限（员工"给张三安排任务"→拒绝；经理→确认流；"我能不能申请远程办公"→结合角色回答；定时任务→System Agent 扫描）
3. **若 test 仍红** → 看 `ci-reports` 失败日志继续修（当前剩 test_operation_audit/test_audit_intelligence，seed_admin 租户修复已提交）
4. 后续（未做）：前端治理看板接入（P5-5 traces/configs/prompts/cost/resilience/health 页面）、Celery 异步管线、技术债务（get_llm 缓存/废弃 server.py）、多部门隔离 department_id 外键落地、`AGENTS.md`（Codex 过期副本）同步/删除定论

**分工**：用户保管并执行所有敏感操作（服务器/密码/SSH/域名/DB/企微凭据）；我只给命令/检查/排障，绝不索要敏感值。详见记忆 `user-ops-split`。

---

# 一、项目目标

## 项目名称

Work Agent


## 项目定位

企业内部智能督导 Agent + 企业知识库管理系统。


## 核心目标

构建一个企业内部智能任务管理助手：

- 管理员 Web 上传知识文档（PDF/Word/Markdown/TXT）
- 自动解析 → 切分 → Embedding → 进入 Milvus
- 接收企业员工企业微信消息
- 检索企业制度知识库，使用大模型生成回复
- 按部门/角色做文档访问权限控制


## 最终架构（guihua.txt 规划）

企业微信 + Web后台 → FastAPI → Service层 → Data层（PostgreSQL/Milvus/MinIO/Redis）
Agent层：LangGraph → Router → RAG Agent / Task Agent


---

# 二、当前技术栈

- Python 3.11.14，uv 管理
- Web：FastAPI + uvicorn
- Agent：LangGraph + LangChain
- LLM：DeepSeek（OpenAI 兼容协议，base_url=https://api.deepseek.com/v1）
- 向量库：Milvus 2.5（docker compose 三件套 etcd+minio+standalone）
- Embedding：BAAI/bge-small-zh-v1.5（512 维）
- 数据库：PostgreSQL 16（docker）+ SQLAlchemy 2.0 同步
- 对象存储：独立 MinIO（docker work-minio，端口 9002）
- 认证：JWT（PyJWT）+ bcrypt
- 任务队列：Celery 已预留（管线异步边界已留替换点）
- 缓存：Redis 已装未用

---

# 三、项目目录结构

```
src/work_agent/
├── agent/               # LangGraph Agent
│   ├── workflow.py      # START→analyze→risk→retrieve→supervision→notify→response→END
│   ├── nodes.py         # 节点逻辑（analyze/risk/retrieve/response）
│   ├── llm.py           # get_llm() DeepSeek 封装
│   ├── state.py         # AgentState
│   ├── supervision.py / supervision_action.py / wechat_notify.py / task_handler.py / router.py
├── rag/                 # RAG（Milvus 版）
│   ├── service.py       # RAGService：search(query, top_k, user_context)
│   ├── milvus_store.py  # MilvusVectorStore（含 insert_documents/delete_by_ids/delete_by_document/search_with_document/count_by_document）
│   ├── loader.py / splitter.py / embedding.py / retriever.py / permission.py
│   ├── answer.py        # 历史硬编码 Prompt（已登记债务，未动）
│   └── vector_store_backup.py  # 旧 FAISS 备份
├── db/                  # SQLAlchemy 2.0 同步
│   ├── base.py / session.py  # engine / SessionLocal / get_db()
│   └── models/          # User / Tenant / Document / KnowledgeChunk / DocumentPermission / AgentLog
├── repositories/        # Repository 层（user/tenant/document/knowledge_chunk/document_permission/agent_log）
├── storage/             # MinIO：MinioStorage + build_object_key（租户隔离路径）
├── document/            # 上传文档管线
│   ├── parser.py        # parse_document：pdf/docx/md/txt
│   └── pipeline.py      # DocumentPipeline：解析→切分→Embedding→Milvus→DB
├── knowledge/           # KnowledgeService：检索 + 文档信息富化（纯召回）
│   │                    # classifier（自动分类）/ graph（知识图谱）/ similarity（相似文档）/ quality（质量分析）
├── services/            # Service 层
│   ├── document_service.py  # DocumentService：upload（异步边界）/delete/list/get
│   └── auth_service.py      # bcrypt 哈希 + JWT
├── api/                 # admin.py（/api/admin 登录/上传/列表/删除/检索）、deps.py、schemas.py
├── wechat/              # 企业微信收发（parser/verify/sender/service）
├── prompts/             # 独立 Prompt 模板（load_prompt(name) 读 prompts/{name}.txt）
├── core/
│   ├── container.py     # 依赖组装（rag/document/knowledge/auth/audit/minio 服务单例）
│   ├── exceptions.py    # TenantAccessDenied 领域异常（API 层转 403）
│   └── audit_logger.py  # 统一审计：AuditLogger.log_request/log_success/log_error + TokenUsageCallback
├── services/audit_service.py  # 审计日志服务（租户隔离分页查询 + 用户名回填）
├── scripts/             # init_db / migrate_tenant / migrate_agent_logs / seed_admin / seed_tenants / seed_knowledge_library / import_knowledge / test_milvus / test_parser / test_permission / test_tenant_admin / test_audit
├── config.py            # pydantic-settings 配置（读 .env）
└── main.py              # FastAPI 入口（含 admin 路由 + wechat 回调 + stdout UTF-8 修复）
```

---

# 四、核心架构决策（不可违反）

1. **Prompt 独立**：代码里禁止硬编码业务 Prompt，统一放 prompts/*.txt
2. **业务解耦分层**：API → Service → Repository → Database；Web 接口不直接调 Milvus；Agent 不操作数据库；RAG 不写权限
3. **不推翻已有 RAG**：只在 rag/ 增量加方法，不动现有方法
4. **knowledge_chunks 表是 Milvus 向量映射的唯一事实源**：删除文档先查 milvus_id 再删向量，document_id 动态字段仅作辅助
5. **多租户预留**：各表带 tenant_id 占位（默认空=单租户）；MinIO 对象 key 保留 tenants/{tenant_id}/documents/ 结构
6. **文档权限前置**：documents.visibility + document_permission 表；管线写入 Milvus chunk metadata 的 access{departments,roles}，与 PermissionFilter 兼容

---

# 五、当前开发阶段

**Phase 1 企业知识库闭环已完成**：

管理员登录 → 上传 PDF/MD → 自动解析 → 自动 Embedding → 进入 Milvus → 员工企业微信提问 → AI 回答

**Phase 2-1 多租户身份与权限链路已完成**：
- tenants 表 + TenantRepository + 迁移脚本（migrate_tenant）
- 企业微信身份链路：FromUserName → users.wechat_user_id → tenant/department/role；未注册返回明确错误
- RAG 检索租户隔离：Milvus 层 `metadata["tenant_id"]` 预过滤 + 部门/角色 Python 层 PermissionFilter
- 三场景权限测试通过（A财务可召回 / A研发被过滤 / B员工0结果）

**安全收尾已完成**：
- DocumentService delete/get 增加 tenant_id 校验，跨租户抛 `TenantAccessDenied` → 全局异常处理器 403
- 越权测试通过：A管理员删B文档→403、A只见自己文档、同租户操作→204

**Web 管理后台（Vue3 + Element Plus）已完成**（`frontend/`）：
- Vite + Vue3 + Element Plus + vue-router + axios
- 页面：/login 登录、/knowledge 知识库管理（上传/列表/检索/详情/删除/状态轮询）、/permission 权限总览、/dashboard 看板、/logs 问答审计
- 开发：`cd frontend && npm run dev`（:5173，/api 代理 :8000）

**Phase 6-1 Production Deployment 已完成**：
- `deploy/`：生产部署体系（`docker-compose.prod.yml` + `nginx/` + `scripts/` + `README.md` 部署手册）
- 架构：宿主机 Nginx（Certbot TLS）→ frontend/dist + /api 代理；Docker 内部网络跑 backend/postgres/milvus/redis/work-minio；数据库/Milvus/MinIO/Redis 不发布端口，backend 仅 127.0.0.1:8000
- 镜像：`Dockerfile`（PYTHONPATH=/app/src、torch-cpu、单 worker、HF 缓存卷不烘焙模型）+ `.dockerignore`（排除密钥/数据/测试内容）
- 依赖：`requirements.prod.txt`（`uv lock` 重建 + `uv export` 生成，torch=+cpu）；`requirements.txt` 保持原样
- 配置：`.env.example` 扩展生产变量；`config.py` 新增 `milvus_uri`/`cors_origins`；`main.py` CORS 配置化（开发 `*` / 生产白名单）
- 脚本：preflight（git无.env/docker/磁盘/端口）、init-server、deploy、update、rollback、init-prod（仅 init_db+seed_admin）
- **阻塞项**：`rag/milvus_store.py` 连 Milvus 地址接线待批准（配置字段已加，业务未改）
- 验证：生产套件 6/6+3/3、前端 build 通过、`docker compose config` 通过、Git 无 .env/密钥
- **服务器部署**：按 `deploy/README.md` 在腾讯云执行（本环境不连接服务器）
- **P5-5-7 Production Test Suite 已完成**：
  - `scripts/test_production_suite.py`：一键运行 6 个 P5-5 子套件（trace/config/prompt_governance/llm_cost/failure_recovery/health）+ 生产契约断言（Agent/Tool 不直连 DB、API 分层、Prompt 外置）
  - 产出 `reports/production_suite_report.json`
  - **Phase 5 Enterprise Agent Platform 全部完成**：Planner → Multi-Agent → 评测 → 知识智能 → 生产治理（Trace/Config/Prompt/Cost/Recovery/Health/Suite），全量回归 28/28
- **P5-5-6 Agent Health Monitoring 已完成**：
  - `core/health_metrics.py`：进程内指标（requests/errors/denied/latency/tokens），Runtime 各终态埋点
  - `services/health_service.py`：组件探活（PG/Milvus/MinIO/Redis/配置中心/Prompt），Redis 可选依赖仅警告，就绪判定 = 关键三依赖
  - API `api/health.py`：GET /health/ready（公共探针）、/api/admin/health/{components,metrics,resilience}（system:manage）
  - 测试 `scripts/test_health_monitoring.py` 五场景（就绪/组件/指标递增/权限/存活），全量回归 27/27
- **P5-5-5 Failure Recovery 已完成**：
  - `core/resilience.py`：retry_with_backoff（瞬时错误指数退避）、CircuitBreaker（closed→open→half_open→closed）、ResilientLLM 透明包装、全局熔断器注册表
  - `agent/llm.py`：get_llm 返回 ResilientLLM（接口不变）；config 新增 `llm_max_retries`/`llm_breaker_failure_threshold`/`llm_breaker_cooldown_seconds`
  - 熔断 open 快速失败（BreakerOpenError）→ 上层 Agent 捕获后走确定性回退，避免在故障服务上反复超时
  - API `api/resilience.py`：GET /api/admin/resilience/status
  - 测试 `scripts/test_failure_recovery.py` 六场景（重试/熔断状态机/重试成功/熔断快速失败/LLM全挂回退/HTTP），全量回归 26/26
- **P5-5-4 LLM Cost Governance 已完成**：
  - `llm_cost_records` 表（tenant_id 隔离、request_id 关联、cost 估算）
  - `services/cost_governance_service.py`：record 记账、usage（今日/本月、按模型/用户）、get/set_budget（复用配置中心 `cost.monthly_budget`）、check_quota
  - Runtime 集成：**预算检查在调用 LLM 之前**，超限 → 优雅消息 + denied 审计（budget_exceeded）+ 不调 LLM；执行完成后按 token_usage 记账（失败静默）
  - API `api/cost.py`：GET /cost/usage、GET/PUT /cost/budget
  - 测试 `scripts/test_llm_cost.py` 六场景（记账聚合/预算/超限拦截/隔离/HTTP），全量回归 25/25
- **P5-5-3 Prompt Governance 已完成**：
  - `prompt_versions` 表（draft/approved/active/deprecated 状态机，tenant_id="" 平台级）
  - `services/prompt_governance_service.py`：seed_from_files 基线、create_draft（版本自增）、approve、activate（唯一 active + 清缓存）、deprecate、回滚
  - PromptManager 治理 resolver：active DB 版本优先，无则回退文件（既有行为不变）
  - 激活写操作审计 `prompt.activate`
  - API `api/prompt.py`：GET /prompts、GET /prompts/{name}/history、POST /prompts/{name}/versions、POST /prompts/{name}/activate、POST /prompts/seed
  - 测试 `scripts/test_prompt_governance.py` 六场景（seed/草稿审批激活/回滚/审计/租户隔离/HTTP），全量回归 24/24
- **P5-5-2 Agent Configuration Center 已完成**：
  - `agent_configs` 表（tenant_id="" 平台级 / 租户级覆盖，JSON 值）+ `core/config_defs.py` 内置默认注册表
  - `services/config_service.py`：取值优先级 租户→平台→内置默认，内存缓存（set 失效）
  - Runtime 集成：planner 从配置中心读 `agent.default_top_k`；`agent.tools.enabled` 停用工具拦截（不执行 Agent，返回治理消息）
  - RBAC 增强：`get_role_codes()`；平台级配置仅 SUPER_ADMIN 可写
  - API `api/config.py`：GET/PUT /api/admin/configs（scope=tenant/platform）
  - 测试 `scripts/test_agent_config.py` 六场景（默认/覆盖/隔离/top_k/停用拦截/平台权限），全量回归 23/23
- **P5-5-1 Agent Trace 已完成**：
  - `core/trace.py`：TraceManager（contextvar 持有当前 trace，span() 嵌套父级关联，内存缓冲 + finish 单事务批量写库，失败静默不影响主链路）
  - 模型 `agent_traces` + `trace_spans`（request_id 唯一、tenant_id 隔离、parent_span_id 瀑布、attributes JSON）
  - Runtime 集成：context_builder/intent_router/planner/supervisor/audit 五阶段 span，request_id 统一注入 AgentContext（与审计对齐）
  - `services/trace_service.py`（租户隔离分页 + 详情 + 瀑布）+ `api/trace.py`（GET /traces、GET /traces/{request_id}）
  - 测试 `scripts/test_agent_trace.py` 五场景（正常执行/跨租户/异常路径/空操作/HTTP），全量回归 22/22
- **P5-4 Knowledge Intelligence 已完成**：
  - `knowledge/classifier.py`：DocumentClassifier（LLM 自动分类，`doc_classifier` Prompt，失败回退人工类别/未分类）
  - 管线自动分类：`document/pipeline.py` 解析后钩入（人工指定类别优先，仅空类别时触发；落库 + 同步 Milvus category）
  - `knowledge/graph.py`：KnowledgeGraphService（实体/关系抽取，`kg_extract` Prompt，LLM 失败回退确定性高频词+共现）
  - 图谱存储：`knowledge_entities` + `knowledge_relations` 表（实体按 tenant+name 唯一合并，关系按文档重建幂等）
  - `knowledge/similarity.py`：SimilarDocumentService（逐 chunk 向量检索，Milvus filter `document_id != N` 排除自身，聚合匹配块/最高分）
  - `knowledge/quality.py`：KnowledgeQualityService（质量体检：overview/chunk_stats/chunk_length/classification/duplicates/consistency/health_score）
  - API：`api/knowledge_intelligence.py`（GET /quality、GET /similar/{id}、GET /graph、POST /graph/build 按需构建），response_model 校验通过
  - config：`knowledge_auto_classify` / `kg_entity_limit`
  - 测试：`scripts/test_knowledge_intelligence.py` 六场景（分类/图谱/相似/质量/跨租户/LLM 回退），HTTP 冒烟通过
  - 全量回归 21/21
- **P5-3 Agent Evaluation System 已完成**：
  - `agent/evaluation/`：dataset（数据加载）+ evaluator（经 AgentRuntime 执行）+ metrics（6 指标）+ report（JSON 报告）
  - Golden Dataset：`evaluation/datasets/agent_cases.json`（50 案例：intent/tool/agent/security/regression 各 10）
  - Runtime 观测字段：agent / plan_kind / tool_calls（additive）+ intent 统一用 IntentRouter
  - 新增 audit_query 意图（audit_tool 可达）
  - 全量评测 50/50 通过，全部指标 1.0（含安全/隔离必须 100%）
  - 报告：`reports/agent_eval_report.json`
  - 测试：`scripts/test_agent_evaluation.py`（六场景）+ `scripts/run_agent_evaluation.py`
  - 全量回归 18/18
- **P5-2 Multi Agent Architecture 已完成**：
  - `agent/agents/`：base(BaseAgent) + schemas(AgentResult) + registry(AgentRegistry) + supervisor(SupervisorAgent) + knowledge_agent/operation_agent/analysis_agent
  - `agent/tools/analysis_tool.py`：风险/任务分析工具（检索制度 + 规则风险评估）
  - Runtime 改造：Context → Intent → Planner → **Supervisor → Agent → Tool** → Audit
  - 计划类型：knowledge→KnowledgeAgent / document→OperationAgent / risk→AnalysisAgent / legacy→旧工作流
  - Agent 规范：不直连 DB（经 Tool）、经 RBAC、写 Audit（Runtime 统一）
  - 测试：`scripts/test_multi_agent.py`（注册表/知识/操作/分析/权限拒绝/跨租户）+ `scripts/test_utils.py`（共享清理，防孤儿向量污染）
  - 全量回归 17/17
- **P5-1 Agent Planner 已完成**：
  - `agent/planner.py`：AgentPlanner（plan 确定性路径 + plan_with_llm 复杂分解，失败回退）
  - `agent/schemas.py`：PlanStep / PlanResult（kind: knowledge/document/legacy）
  - `prompts/workflow_planner.txt`：任务规划 Prompt（已注册 v1.0）
  - Runtime：Planner 阶段接入（plan.kind 决定执行路径，工具按 plan.steps 执行）
  - 测试：`scripts/test_agent_planner.py`（知识/文档/督导计划 + LLM 规划 + Runtime 集成），全量回归 16/16
- **Phase 4 Agent Intelligence（全部完成 ✅）**：
- **P4-7 完整测试已完成**：
  - `scripts/test_agent_intelligence.py` 五场景：知识查询 / 权限不足 denied / 文档操作 Tool Router / LLM 异常 fallback / 跨租户攻击
  - 工具增强：DocumentTool/PermissionTool 捕获 TenantAccessDenied → 干净 permission_denied（跨租户不再 500）
  - 完整回归 15/15 全通过
- **P4-6 Audit 集成已完成**：
  - `agent_logs` 新增字段：agent_version/model_name/prompt_version/intent_confidence/tools_called
  - 迁移：`scripts/migrate_agent_intelligence.py`
  - audit_logger：log_request 记录 agent_version/model_name；log_success 记录 prompt_version/intent_confidence/tools_called
  - Runtime：知识路径 tools_called=['knowledge_tool']，工具路径=[工具名]；LogOut schema 返回新字段
  - 测试：`scripts/test_audit_intelligence.py`（字段落库 + /logs API），回归全通过
- **P4-5 Agent Context 已完成**：
  - `conversations` 表 + ConversationRepository + ConversationService（按 租户+用户+渠道 复用会话）
  - `agent/context.py` 扩展：model_name/agent_version + to_audit_fields()（P4-6 就绪）
  - Runtime：会话 get_or_create + 活动 touch（message_count 递增）+ 结果返回 conversation_id
  - config：`agent_version`
  - 测试：`scripts/test_agent_context.py`（会话连续性/消息递增/不同用户隔离/上下文字段），回归全通过
- **P4-4 Tool Calling 已完成**：
  - `agent/tools/`：document_tool（列表/查看/删除/上传，权限映射）+ permission_tool（权限管理）+ audit_tool（审计查询）
  - `agent/tools/registry.py`：ToolRegistry（4 工具注册/查询/清单）
  - `agent/tools/selector.py`：ToolSelector（tool_selector prompt + 确定性回退）
  - `prompts/tool_selector.txt`：工具选择 Prompt（已注册 v1.0）
  - Runtime：Context 注入 RBAC 权限解析；document_operation 路由到 Tool Executor；工具结果格式化
  - 测试：`scripts/test_tool_calling.py`（注册表/路由/权限强制/权限修改/回退），回归全通过
- **P4-3 Agent Runtime 已完成**：
  - `agent/runtime.py`：AgentRuntime 统一执行管道（Context Builder → Intent Router → Planner → Tool Executor → Response Generator → Audit Logger）
  - `agent/context.py`：AgentContext（request_id/tenant_id/user_id/department/role/permissions/conversation_id/channel）
  - `agent/tools/`：BaseTool 抽象 + KnowledgeTool（经 RAGService，禁止直连 DB）
  - `prompts/knowledge_answer.txt`：知识回答 Prompt（已注册 metadata v1.0）
  - 路径分流：knowledge_query→Tool；督导/风险→旧 LangGraph 工作流（懒加载避免循环依赖）
  - `wechat/service.py` 重构：只保留微信协议/身份解析，Agent 编排交给 Runtime；未注册用户仍记 denied 审计
  - Token 用量经 TokenUsageCallback 跟踪
  - 回归：test_audit（intent 升级为 knowledge_query）/test_permission/test_tenant_admin/test_security_regression/test_intent_router 全通过
- **P4-2 Prompt Management 已完成**：
  - `core/prompt_manager.py`：PromptManager（load/version/cache/list_prompts），业务统一走 PromptManager，禁止直接 open txt
  - `prompts/metadata.py`：Prompt 注册表（版本/描述/变量），已注册 10 个 Prompt，支持未来 A/B 测试/灰度
  - `prompts/loader.py`：重构为 PromptManager 门面（load_prompt 保持兼容返回 content）
  - `intent_router.py`：迁移为 prompt_manager.load()，记录 last_prompt_version
  - 异常：`PromptNotFoundError` / `PromptVersionError`
  - 配置：`PROMPT_PATH`（默认 src/work_agent/prompts）、`PROMPT_CACHE_ENABLED`
  - 测试：`scripts/test_prompt_manager.py`（加载/缓存/不存在/版本），Intent Router 行为无变化，回归通过
- **P4-1 Intent Router 已完成**：
  - `agent/schemas.py`：IntentResult Pydantic 结构化输出（intent/confidence/entities/need_tool/tool/reasoning）
  - `agent/router/intent_router.py`：LLM 意图路由（6 类意图 + 工具映射 + 置信度阈值 + LLM 异常规则回退）
  - `prompts/intent_router.txt`：独立 Prompt（不硬编码）
  - 旧规则 `router.py` 移入 `agent/router/legacy.py`（向后兼容导出 router_node）
  - 测试：`scripts/test_intent_router.py`（LLM 分类 + 回退），回归通过

**Phase 3 Architecture Review（企业级架构审查）已完成 → PASS**：
- 分层修复：RBACService 改为经 `repositories/rbac_repository.py` 访问数据（不再直接 DB 查询）
- 安全测试：`scripts/test_security_regression.py`（跨租户查询/改权限/归档 → 403 或空）
- 索引补齐：`scripts/migrate_indexes.py`（agent_logs/operation_logs/documents/roles/document_permission）
- 审计补齐：归档端点记录 `audit.archive` 操作日志
- 配置收紧：config.py 移除弱口令默认值（强制 .env 提供）；新增 `.env.example` 生产模板
- 完整报告：`architecture_review.md`

**Phase 3-2 企业级运营与治理**：
- Dashboard 驾驶舱：`GET /api/admin/dashboard/stats`（文档/问答/安全/租户/用量统计，租户隔离），DashboardService + 前端真实接口 + test_dashboard.py
- 审计生命周期：`archived_at` 字段 + AUDIT_LOG_RETENTION_DAYS 配置 + `scripts/archive_audit_logs.py`（标记归档/--purge 硬删除）+ `GET /audit/statistics` + `POST /audit/archive` + 前端 /logs 统计栏 + test_audit_lifecycle.py
- 操作审计：`operation_logs` 表 + `AuditService.log_operation`（登录成功/失败、上传、删除埋点）+ `GET /operations` + 前端 /operations 操作审计页 + test_operation_audit.py
- RBAC 权限模型：roles/permissions/role_permissions/user_roles 4 表 + 四角色（SUPER_ADMIN/TENANT_ADMIN/DEPARTMENT_ADMIN/USER）+ 6 权限码 + `require_permission` 依赖 + 端点改造 + `scripts/seed_rbac.py` + test_rbac.py
- 权限管理增强：document_permission 加 user_id（指定用户）+ PermissionService（改权限→DB+Milvus metadata 同步）+ `GET/PUT /documents/{id}/permissions` + PermissionFilter 支持 user_ids + 前端 Permission.vue 编辑功能 + test_permission_management.py

**Phase 3-1 企业级审计与可观测性已完成**：
- `core/audit_logger.py` 统一审计模块：log_request/log_success/log_error + TokenUsageCallback（聚合 LLM token）
- agent_logs 表补充字段（request_id/channel/department/role/intent/status/error_type/error_message/retrieval_documents/latency_ms/token_usage），迁移脚本 migrate_agent_logs
- wechat/service.py 全链路审计：request_id → 身份 → 权限 → RAG → 回答 → success/failed/denied
- RAGService.search_with_meta 检测权限拒绝（candidates>0 但全被过滤 → permission_denied）
- /logs API：按租户隔离分页查询 + 过滤（user/channel/status/时间）
- 前端 /logs 问答审计页（列表/详情/分页/过滤）
- 四场景审计测试通过（tenant_id正确/跨租户隔离/denied/failed）

## 已验证

✅ 9 个种子制度文档经管线导入（DB + MinIO + Milvus 一致，各 1 chunk）
✅ admin API：登录/JWT、上传（异步管线）、列表、详情（含权限+切片）、删除（Milvus+DB+MinIO 三清）、知识检索
✅ 4 种格式解析：md/docx/pdf/txt；坏 PDF → status=failed + error_message
✅ Phase1 权限：财务部员工能检索到受限文档，无关部门被过滤
✅ Phase2-1 权限三场景：A财务可召回 / A研发被过滤 / B员工0结果
✅ 企业微信身份链路：已注册用户正常问答，未注册用户返回明确错误
✅ 企业微信闭环：提问"财务报销制度是什么" → 正确检索并引用制度原文回答
✅ 错误处理：管线失败 → failed + 回滚 Milvus 向量

## 端口与容器

- Milvus：19530 / 9091
- PostgreSQL：5432（容器 work-postgres，库 work_agent，账号 postgres/postgres）
- MinIO：9002（API）/ 9001（console），bucket work-documents，账号 minioadmin/minioadmin
- API 服务：uvicorn work_agent.main:app --port 8000

## 常用命令

```bash
# 启动依赖容器
docker compose up -d

# 建表
python -m work_agent.scripts.init_db

# 初始管理员（admin/admin123，见 .env）
python -m work_agent.scripts.seed_admin

# 租户迁移 + 测试租户/员工
python -m work_agent.scripts.migrate_tenant
python -m work_agent.scripts.seed_tenants

# 审计日志表字段迁移
python -m work_agent.scripts.migrate_agent_logs
python -m work_agent.scripts.migrate_agent_intelligence   # 智能体审计字段
python -m work_agent.scripts.migrate_user_profile         # 用户 real_name + 企微绑定唯一索引（幂等）

# RBAC 角色权限初始化
python -m work_agent.scripts.seed_rbac

# 生产级索引迁移
python -m work_agent.scripts.migrate_indexes

# 审计日志归档（标记过期日志；--purge 硬删除）
python -m work_agent.scripts.archive_audit_logs

# 种子知识库导入（--reset 会先清理旧孤儿 chunk）
python -m work_agent.scripts.seed_knowledge_library --reset

# 测试
python -m work_agent.scripts.run_all_tests                # 一键全量 45 脚本（预建 schema+种子，--only/--skip/--no-setup 可选）
python -m work_agent.scripts.test_permission              # 权限三场景
python -m work_agent.scripts.test_tenant_admin            # 租户越权
python -m work_agent.scripts.test_audit                   # 审计四场景
python -m work_agent.scripts.test_dashboard               # 驾驶舱统计
python -m work_agent.scripts.test_audit_lifecycle         # 审计生命周期
python -m work_agent.scripts.test_operation_audit         # 操作审计
python -m work_agent.scripts.test_rbac                    # RBAC
python -m work_agent.scripts.test_permission_management   # 权限管理
python -m work_agent.scripts.test_security_regression     # 多租户安全回归
python -m work_agent.scripts.test_intent_router           # Intent Router
python -m work_agent.scripts.test_prompt_manager          # Prompt Manager
python -m work_agent.scripts.test_tool_calling            # Tool Calling
python -m work_agent.scripts.test_agent_context           # Agent Context
python -m work_agent.scripts.test_audit_intelligence      # 审计智能体字段
python -m work_agent.scripts.test_agent_intelligence      # Agent 智能体完整测试（五场景）
python -m work_agent.scripts.test_agent_planner           # Agent Planner
python -m work_agent.scripts.test_multi_agent             # Multi Agent
python -m work_agent.scripts.test_agent_evaluation        # Agent 评测系统
python -m work_agent.scripts.run_agent_evaluation         # 运行完整评测（50 案例）
python -m work_agent.scripts.test_knowledge_intelligence  # P5-4 知识智能（分类/图谱/相似/质量）
python -m work_agent.scripts.test_agent_trace             # P5-5-1 链路追踪
python -m work_agent.scripts.test_agent_config            # P5-5-2 配置中心
python -m work_agent.scripts.test_prompt_governance       # P5-5-3 Prompt 治理
python -m work_agent.scripts.test_llm_cost                # P5-5-4 成本治理
python -m work_agent.scripts.test_failure_recovery        # P5-5-5 故障恢复
python -m work_agent.scripts.test_health_monitoring       # P5-5-6 健康监控
python -m work_agent.scripts.test_production_suite        # P5-5-7 生产套件（6 子套件 + 契约）
python -m work_agent.scripts.test_task_reminder           # 任务自动督办（Phase 3）
python -m work_agent.scripts.test_user_management         # 用户管理增强（新建/编辑/real_name/并发加固）
python -m work_agent.scripts.test_task_stats              # 任务统计/周报/邮件（Phase 4）
python -m work_agent.scripts.test_document_consistency   # 文档 PG/Milvus 一致性（删除-管线竞态修复）
python -m work_agent.scripts.test_tenant_global_docs     # 租户语义：空租户文档全局可见（企微查不到 Web 文档修复）
python -m work_agent.scripts.test_enterprise_agent       # Enterprise Agent（工具权限/用户/通知/部门/任务创建确认/意图）
python -m work_agent.scripts.test_task_reminder_extended # 督办增强（staleness/部门 digest/周报部门投递）
python -m work_agent.scripts.test_rag_memory            # RAG 会话记忆（历史/rewrite/统一上下文/隔离容错）
python -m work_agent.scripts.test_policy                 # 企业任务决策层（Policy RBAC：三角色权限/confirm双用途/system）
python -m work_agent.scripts.test_validator              # Task Command Validator（结构/业务规则校验）
python -m work_agent.scripts.test_task_flow              # Task Lifecycle 状态机（转移/取消/超管权限）
python -m work_agent.scripts.test_knowledge_enterprise   # Enterprise Knowledge（权限类问题结合用户画像）
python -m work_agent.scripts.test_system_agent           # System Proactive Agent（system 权限/主动扫描）
python -m work_agent.scripts.migrate_conversation_messages # 会话消息表迁移（幂等）

# 启动服务
python -m uvicorn work_agent.main:app --host 127.0.0.1 --port 8000
```

---

# 六、下一步开发计划

当前完成：Phase 1 闭环、Phase 2 多租户、Phase 3-1 审计、Phase 3-2 企业治理（驾驶舱/审计生命周期/操作审计/RBAC/权限管理）。

**Phase 5（Enterprise Agent Platform）已完成**：Planner → Multi-Agent → 评测系统 → 知识智能。

**下一优先级**
1. **前端接入 P5-4**：知识图谱可视化页 + 知识质量看板页（数据接口已就绪）
2. **企业微信正式接入**：wechat/verify.py 签名校验目前是假的（直接回显 echostr）；sender 已可发消息但 notify 节点只 print
3. **Celery 替换异步管线**：DocumentService._dispatch 是唯一替换点
4. **前端菜单按权限过滤**：RBAC 权限码驱动菜单显示
5. **生产部署**：docker-compose 加 nginx + frontend + 审计卷

---

# 七、已登记的技术债务

- `rag/answer.py` 硬编码中文 Prompt（违反铁律1，启用时迁移到 prompts/rag_answer.txt）
- `wechat/verify.py` 签名校验未实现（当前原样回显 echostr）
- `agent/llm.py` 配置字段名 doubao_api_key 实际承载 DeepSeek key（命名遗留）
- `api/server.py` 是废弃重复 app（入口是 main.py）
- agent 各节点多次 get_llm() 新建实例，无缓存
