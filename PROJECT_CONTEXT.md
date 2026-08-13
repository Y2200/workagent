# Work Agent 项目上下文

> 本文档用于项目开发上下文迁移。
> 新对话开始时，将此文件提供给 AI，使其快速了解项目目标、当前架构、已完成模块和下一步开发计划。


---

# ⚡ 当前状态（2026-08-13，任务督导第二轮优化完成）

**代码状态**：本地 `master` 工作区有未提交改动（任务督导模块）。生产已上线：`https://wkcp.online`（前端）、`https://api.wkcp.online`（API）。企微链路全通（验签/解密/身份/Agent/回复），Milvus 租户元数据修复已上线。

**任务督导（AI Task Supervisor）MVP —— 完成，回归全绿 31/31**：
- 模型：`tasks`/`task_updates`/`task_pending_updates` 三表（`db/models/task.py` + `scripts/migrate_tasks.py`）
- 服务：`repositories/task_repository.py` + `services/task_service.py`（创建/查询/提交/确认/取消，AI 解析 `task_progress_parse` prompt + 确定性回退）
- Agent：`agent/agents/task_agent.py` + `agent/tools/task_tool.py`（list/submit/confirm/cancel/complete）；新意图 `task_management`
- 接入：intent_router prompt/规则、planner（kind=task + 任务消息归一化）、agent_registry/tool_registry 注册
- **AI 确认机制**：员工提交 → AI 解析进度/摘要 → 写 pending（不落正式表）→ 回复「确认提交吗？」→ 员工回「确认」→ 落 task_updates + 更新 tasks.progress（完成=100）
- Web：`api/tasks.py`（列表/创建/详情/负责人下拉 `task/employees`）+ 前端 `Tasks.vue`（创建/列表/详情/提交记录）
- 权限：`task:view`/`task:create`/`task:manage` 加入 seed_rbac
- 测试：`scripts/test_task_agent.py` 四部分（服务层/意图规划/Agent端到端/越权隔离）

**任务督导第二轮优化 —— 完成（5 Phase 全绿，test_task_agent 11 部分）**：
- Phase1 任务上下文路由：短任务名直接进任务Agent（归一化精确→embedding相似，不用 contains；含动作词短句不误判）；新 action=detail
- Phase2 提交解析优化：提交=操作指令/任务名≠summary/无内容="未提供具体完成内容"
- Phase3 批量提交：submit_all（全部未完成任务→批量预览→确认批量更新）
- Phase4 Web 发布任务企微提醒：NotificationService.send_task_created（失败不影响任务创建）
- Phase5 通知记录表：task_notifications（pending/sent/failed，含 sent_at）

- 未做（后续）：自动提醒/风险（APScheduler）、Excel/Word/邮件、周报

**下一步**：
1. commit + push 任务督导改动
2. 服务器侧：`git pull` → `migrate_tasks`（建表）→ `seed_rbac`（task 权限）→ `deploy.sh`（重建镜像）
3. Web 登录 `https://wkcp.online` → 「任务管理」创建任务 → 员工企微「我的任务」可见
4. 后续：APScheduler 自动督办、任务统计/周报/邮件（6-2.txt Phase 3/4）

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

# RBAC 角色权限初始化
python -m work_agent.scripts.seed_rbac

# 生产级索引迁移
python -m work_agent.scripts.migrate_indexes

# 审计日志归档（标记过期日志；--purge 硬删除）
python -m work_agent.scripts.archive_audit_logs

# 种子知识库导入（--reset 会先清理旧孤儿 chunk）
python -m work_agent.scripts.seed_knowledge_library --reset

# 测试
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
