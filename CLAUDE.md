# Work Agent 项目 — 会话恢复指南

> 本文件由 Claude Code 每次会话启动时自动加载。
> 新会话从"继续开发"开始即可，无需重新描述项目。

## 快速恢复（3 个必读文件）

| 文件 | 作用 |
|------|------|
| **`PROJECT_CONTEXT.md`** | 项目活文档：目标/架构/已完成阶段/下一步/常用命令。**每次新会话必读** |
| **`guihua.txt`** | 总体规划（架构/分层铁律/开发顺序） |
| **`errors.txt`** | 全部历史问题记录（每个问题含原因/解决方案/验证方式） |
| **`architecture_review.md`** | 架构审查结果（分层/多租户安全/索引） |

## 当前状态（v0.5-agent-platform 里程碑）

- **已完成**：Phase 1（知识库闭环）→ Phase 2（多租户）→ Phase 3-1（审计）→ Phase 3-2（运营治理）→ 架构审查 PASS → Phase 4（Agent 智能化：IntentRouter/PromptManager/Runtime/ToolCalling/Context/Audit）→ **Phase 5（Planner/MultiAgent/Evaluation/Knowledge Intelligence 已完成）→ P5-5 Enterprise Production Hardening（进行中）**
- **P5-4 Knowledge Intelligence**：管线自动分类（人工类别优先）、知识图谱（LLM 抽取+确定性回退）、相似文档检测、质量分析（`/api/admin/knowledge/*`）
- **P5-5-1 Agent Trace**：请求链路追踪（agent_traces/trace_spans + TraceManager + Runtime 五阶段 span + `/api/admin/traces`）
- **P5-5-2 Agent Configuration Center**：配置中心（agent_configs + config_service + 内置默认 + 租户/平台级覆盖 + 工具停用拦截 + `/api/admin/configs`）
- **P5-5-3 Prompt Governance**：Prompt 生命周期（prompt_versions + seed 基线 + 草稿/审批/激活/回滚 + PromptManager 治理 resolver + `/api/admin/prompts`）
- **下一步**：P5-5-4 Cost → P5-5-5 Recovery → P5-5-6 Health → P5-5-7 Suite（见 PROJECT_CONTEXT.md）
- **测试状态**：24/24 全绿（`python -m work_agent.scripts.test_<name>`，见 PROJECT_CONTEXT.md）
- **评测**：Agent 评测 50/50 全绿，报告在 `reports/agent_eval_report.json`

## 架构铁律（不可违反）

1. **分层**：API → Service → Repository → DB；Agent → Router → Tool → Service
2. **Prompt 外置**：代码禁止硬编码业务 Prompt，统一经 `core/prompt_manager.py`（`prompts/` 目录）
3. **多租户隔离**：所有数据查询必须按 `tenant_id` 过滤
4. **权限**：Agent 执行必须经 RBAC（`require_permission`）；RAG 检索经 `PermissionFilter`
5. **审计**：Agent 执行必须写 Audit（`core/audit_logger.py`）
6. **Tool 禁直连 DB**：工具只经 Service
7. **开发节奏**：每阶段 = 写测试 + 全量回归 + 更新 PROJECT_CONTEXT.md + 错误写入 errors.txt

## 运行环境

- 后端：`python -m uvicorn work_agent.main:app --host 127.0.0.1 --port 8000`
- 前端：`cd frontend && npm run dev`（:5173，/api 代理到 :8000）
- 依赖容器：`docker compose up -d`（PostgreSQL/MinIO/Milvus）
- 数据库建表/迁移/种子：见 PROJECT_CONTEXT.md 常用命令
- 环境：Windows，Python 3.11（.venv），uv 管理

## 敏感文件

- `.env` 含真实密钥，**已被 .gitignore 排除，绝不提交**；配置模板见 `.env.example`
