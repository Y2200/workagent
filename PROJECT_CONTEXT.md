# Work Agent 项目上下文

> 本文档用于项目开发上下文迁移。
> 新对话开始时，将此文件提供给 AI，使其快速了解项目目标、当前架构、已完成模块和下一步开发计划。


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

**Phase 5 Enterprise Agent Platform（进行中）**：
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

# 启动服务
python -m uvicorn work_agent.main:app --host 127.0.0.1 --port 8000
```

---

# 六、下一步开发计划

当前完成：Phase 1 闭环、Phase 2 多租户、Phase 3-1 审计、Phase 3-2 企业治理（驾驶舱/审计生命周期/操作审计/RBAC/权限管理）。

**下一优先级（Phase 4）**
1. **Agent 智能化升级**：LLM Intent Router、Tool Calling、多 Agent 协作、企业知识分析、风险识别、自动工作流
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
