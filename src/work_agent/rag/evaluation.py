"""
RAG 检索评测与响应质量评估（结合业务场景）

能力：
- Golden case 加载（evaluation/datasets/rag_cases.json）
- 测试文档内存导入（EVAL* 前缀，自包含，不依赖磁盘 knowledge/）
- 检索指标：hit@k / recall@k / MRR / 权限拒 / 租户隔离 / 全局文档
- 场景断言区分「权限拒」与「检索漏」（用候选源集合证明）
- top_k 调优 sweep（3/5/8，传参覆盖硬编码，不改生产代码）
- LLM-as-judge 响应质量（--judge 可选，Prompt 外置）
- 报告输出 reports/rag_eval_report.json

仅供评测脚本导入（test_rag_evaluation / run_rag_evaluation），不参与生产运行链路。
"""

import json
import time

from datetime import datetime
from pathlib import Path

from work_agent.config import BASE_DIR
from work_agent.core.container import document_service, rag_service
from work_agent.core.utils import build_tenant_filter, safe_parse_json
from work_agent.db.models import Document
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository


DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "datasets"
    / "rag_cases.json"
)

DEFAULT_REPORT_PATH = (
    Path(BASE_DIR)
    / "reports"
    / "rag_eval_report.json"
)

EVAL_PREFIX = "EVAL"


# ======================
# 评测测试文档（内存，自包含）
# 每篇 150-400 字、单一主题、独特词只在本文档出现，
# 稳定压过 Milvus score_threshold=0.55（bge 中文匹配度通常 0.6-0.85）
# ======================

DOC_SPECS = {
    "EVAL财务报销制度.md": {
        # tenant_key: A=租户A, G=空租户（全局可见）
        "tenant_key": "A",
        "visibility": "restricted",
        "departments": ["财务部"],
        "roles": [],
    },
    "EVAL采购审批制度.md": {
        "tenant_key": "A",
        "visibility": "restricted",
        "departments": ["采购部"],
        "roles": [],
    },
    "EVAL请假审批制度.md": {
        "tenant_key": "A",
        "visibility": "public",
        "departments": [],
        "roles": [],
    },
    "EVAL日报管理制度.md": {
        "tenant_key": "G",
        "visibility": "public",
        "departments": [],
        "roles": [],
    },
}

DOC_CONTENTS = {
    "EVAL财务报销制度.md": (
        "# 财务报销制度\n"
        "\n"
        "一、适用范围\n"
        "本制度适用于全体员工，所有报销事项必须遵守本制度。\n"
        "\n"
        "二、报销流程\n"
        "员工发生费用后填写报销单，粘贴发票，提交部门负责人审批；"
        "审批通过后由财务部复核，财务部确认发票和付款凭证无误后安排打款。\n"
        "\n"
        "三、报销标准\n"
        "差旅费、办公费、招待费按照财务报销标准执行，超过标准的费用不予报销；"
        "报销单必须附发票，缺少发票的报销单不予受理。\n"
        "\n"
        "四、报销时间\n"
        "每月25日前提交当月报销单，逾期顺延至下月。"
    ),
    "EVAL采购审批制度.md": (
        "# 采购审批制度\n"
        "\n"
        "一、适用范围\n"
        "本制度适用于公司采购业务，所有采购事项必须遵守本制度。\n"
        "\n"
        "二、采购流程\n"
        "采购需求提出后填写采购申请单，采购部负责询价、比价，"
        "选择供应商后签订采购合同，合同金额超过五万元需总经理审批。\n"
        "\n"
        "三、采购原则\n"
        "采购必须经过询价和比价，择优选择供应商；签订采购合同后方可付款。\n"
        "\n"
        "四、采购验收\n"
        "货物到货后由采购部组织验收，验收合格办理入库。"
    ),
    "EVAL请假审批制度.md": (
        "# 请假审批制度\n"
        "\n"
        "一、适用范围\n"
        "本制度适用于全体员工，所有请假事项必须遵守本制度。\n"
        "\n"
        "二、请假类型\n"
        "年假、病假、事假、婚假等各类请假均需提前提出申请。\n"
        "\n"
        "三、请假流程\n"
        "员工填写请假单，说明请假原因和时间，提交部门负责人审批；"
        "请病假需提供医院证明，请年假需提前三天提出申请。\n"
        "\n"
        "四、请假管理\n"
        "请假期限按公司规定执行，未经审批擅自休假按旷工处理。"
    ),
    "EVAL日报管理制度.md": (
        "# 日报管理制度\n"
        "\n"
        "一、适用范围\n"
        "本制度适用于全体员工，所有员工每天必须提交工作日报。\n"
        "\n"
        "二、日报内容\n"
        "日报须写明今日完成工作、明日计划、遇到的问题，通过企业微信提交。\n"
        "\n"
        "三、提交时间\n"
        "每日下班前提交当日日报，未按时提交按未完成处理。\n"
        "\n"
        "四、日报管理\n"
        "部门负责人次日查看部门日报，汇总后上报管理层。"
    ),
}


def load_cases(path: str | None = None) -> list[dict]:
    """
    加载 golden 评测集
    """
    p = Path(path or DATASET_PATH)
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("cases", [])


# ======================
# 环境准备 / 清理
# ======================

def _tenant_id(corp_id: str) -> str:
    db = SessionLocal()
    try:
        return str(TenantRepository().get_by_corp_id(db, corp_id).id)
    finally:
        db.close()


def _wait_ready(document_id: int, timeout: float = 90.0) -> str:
    db = SessionLocal()
    try:
        start = time.time()
        while time.time() - start < timeout:
            db.expire_all()
            doc = DocumentRepository().get_by_id(db, document_id)
            if doc and doc.status in ("ready", "failed"):
                return doc.status
            time.sleep(1)
        return "timeout"
    finally:
        db.close()


def _cleanup_start() -> None:
    """
    清理历史残留：租户1/2 数据 + 本评测 EVAL* 孤儿（含空租户）

    空租户文档不在 cleanup_tenant_data 覆盖范围，必须显式删。
    """
    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    # Milvus：EVAL* 孤儿向量（含空租户）
    store = rag_service.store
    ids = [
        row["id"]
        for row in store.client.query(
            collection_name=store.COLLECTION_NAME,
            filter=f'source like "{EVAL_PREFIX}%"',
            output_fields=["id"],
            limit=16384,
            consistency_level="Strong",
        )
    ]
    if ids:
        store.client.delete(
            collection_name=store.COLLECTION_NAME,
            ids=ids,
            consistency_level="Strong",
        )
        store.client.flush(store.COLLECTION_NAME)

    # DB：EVAL* 空租户文档
    db = SessionLocal()
    try:
        for doc in db.query(Document).filter(
                Document.tenant_id == "",
                Document.filename.like(f"{EVAL_PREFIX}%"),
        ):
            document_service.delete(doc.id, tenant_id="")
    finally:
        db.close()


def setup(tenant_a: str, tenant_b: str) -> list:
    """
    导入 4 篇评测文档并等待就绪

    返回 Document 对象列表（供 cleanup 用）
    """
    from work_agent.scripts.seed_tenants import seed_tenants

    seed_tenants()
    _cleanup_start()

    docs = []
    for filename, spec in DOC_SPECS.items():
        tenant = "" if spec["tenant_key"] == "G" else tenant_a
        doc = document_service.upload(
            filename=filename,
            data=DOC_CONTENTS[filename].encode("utf-8"),
            # 必传非空 category：否则管线触发 LLM 自动分类（慢/不稳定/烧 token）
            category="制度",
            uploader="eval",
            tenant_id=tenant,
            visibility=spec["visibility"],
            departments=spec["departments"],
            roles=spec["roles"],
        )
        docs.append(doc)

    for doc in docs:
        status = _wait_ready(doc.id)
        if status != "ready":
            raise RuntimeError(
                f"评测文档处理失败: {doc.filename} status={status}"
            )

    return docs


def cleanup(docs: list, tenant_a: str = "") -> None:
    """
    删除评测文档 + 清租户残留 + 扫 EVAL* 孤儿

    cleanup_tenant_data 不覆盖空租户，日报文档（tenant_id=""）必须显式删。
    """
    for doc in docs:
        tenant = "" if doc.tenant_id == "" else doc.tenant_id
        try:
            document_service.delete(doc.id, tenant_id=tenant)
        except Exception:
            pass

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()
    _cleanup_start()


# ======================
# 检索 / 指标
# ======================

def _real_tenant(case_tenant: str, tenant_a: str, tenant_b: str) -> str:
    if case_tenant == "1":
        return tenant_a
    if case_tenant == "2":
        return tenant_b
    return case_tenant


def _candidate_sources(query: str, tenant_filter: str, top_k: int = 100) -> set[str]:
    """
    取租户过滤后、权限过滤前的候选来源集合

    用于区分「权限拒」与「检索漏」：被拒文档应在候选源里、但不在最终结果里。
    """
    candidates = rag_service.retriever.search(
        query,
        top_k=top_k,
        filter=tenant_filter,
    )
    return {c.get("source", "") for c in candidates}


def run_case(case: dict, top_k: int, tenant_a: str, tenant_b: str) -> dict:
    """
    执行单个 golden case，返回含指标/明细的结果 dict
    """
    real_tenant = _real_tenant(case.get("tenant_id", ""), tenant_a, tenant_b)
    user_context = {
        "tenant_id": real_tenant,
        "department": case.get("department", ""),
        "role": case.get("role", ""),
    }

    meta = rag_service.search_with_meta(
        case.get("query", ""),
        top_k=top_k,
        user_context=user_context,
    )
    results = meta["results"]
    denied = meta["denied"]
    result_srcs = {r.get("source", "") for r in results}
    expected = set(case.get("expected_documents", []))
    denied_docs = set(case.get("denied_documents", []))
    cand_srcs = _candidate_sources(
        case.get("query", ""),
        build_tenant_filter(real_tenant),
    )

    scenario = case.get("scenario", "")
    rank = 0
    check = scenario

    if scenario in ("normal", "global_doc"):
        # 期望文档必须在最终结果里
        ok = bool(expected) and expected <= result_srcs
        rank = next(
            (i + 1 for i, r in enumerate(results) if r.get("source") in expected),
            0,
        )
    elif scenario == "permission_deny":
        # 被拒文档不在结果 + denied 标志为真 + 被拒文档确为候选
        # → 证明是权限过滤生效，而非检索漏掉
        ok = (
            denied_docs.isdisjoint(result_srcs)
            and denied is True
            and denied_docs <= cand_srcs
        )
    elif scenario == "cross_tenant":
        # 租户隔离在 Milvus 层生效：不在结果也不在候选
        ok = (
            denied_docs.isdisjoint(result_srcs)
            and denied_docs.isdisjoint(cand_srcs)
        )
        # 反证：该文档在 owner 租户过滤下本可被检索到
        if ok and denied_docs:
            ok = denied_docs <= _candidate_sources(
                case.get("query", ""),
                build_tenant_filter(tenant_a),
            )
    else:
        ok = False

    return {
        "case_id": case.get("id", ""),
        "scenario": scenario,
        "query": case.get("query", ""),
        "expected_documents": sorted(expected),
        "denied_documents": sorted(denied_docs),
        "tenant_id": real_tenant,
        "department": case.get("department", ""),
        "role": case.get("role", ""),
        "passed": ok,
        "check": check,
        "hit_at_k": (rank > 0) if expected else True,
        "recall_at_k": 1.0 if (expected and expected <= result_srcs) else 0.0,
        "rank_first_expected": rank,
        "mrr_contribution": (1.0 / rank) if rank else 0.0,
        "candidates": meta["candidates"],
        "denied": denied,
        "results": [
            {
                "source": r.get("source", ""),
                "score": round(float(r.get("score", 0)), 4),
                "rank": i + 1,
            }
            for i, r in enumerate(results)
        ],
    }


def compute_metrics(results: list[dict]) -> dict:
    """
    聚合指标（各场景独立分母）
    """
    def _mean(values) -> float:
        values = list(values)
        return round(sum(values) / len(values), 4) if values else 0.0

    hit_cases = [r for r in results if r["expected_documents"]]
    permission_cases = [r for r in results if r["scenario"] == "permission_deny"]
    tenant_cases = [r for r in results if r["scenario"] == "cross_tenant"]
    global_cases = [r for r in results if r["scenario"] == "global_doc"]

    return {
        "hit_at_k": _mean(r["hit_at_k"] for r in hit_cases),
        "recall_at_k": _mean(r["recall_at_k"] for r in hit_cases),
        "mrr": _mean(r["mrr_contribution"] for r in hit_cases),
        "permission_deny_accuracy": _mean(r["passed"] for r in permission_cases),
        "tenant_isolation_accuracy": _mean(r["passed"] for r in tenant_cases),
        "global_doc_accuracy": _mean(r["passed"] for r in global_cases),
    }


def top_k_sweep(
        cases: list[dict],
        tenant_a: str,
        tenant_b: str,
        ks: tuple = (3, 5, 8),
) -> list[dict]:
    """
    top_k 调优对比实验（传参覆盖硬编码，不改生产代码）
    """
    sweep = []
    for k in ks:
        results = [run_case(c, k, tenant_a, tenant_b) for c in cases]
        metrics = compute_metrics(results)
        sweep.append({
            "top_k": k,
            "hit_at_k": metrics["hit_at_k"],
            "recall_at_k": metrics["recall_at_k"],
            "mrr": metrics["mrr"],
            "passed": sum(1 for r in results if r["passed"]),
            "total": len(results),
        })
    return sweep


# ======================
# 响应质量评估（--judge 可选）
# ======================

_DOMAIN_KEYWORDS = (
    "报销", "发票", "付款凭证", "报销单",
    "采购", "询价", "比价", "采购合同",
    "请假", "年假", "病假", "医院证明",
    "日报", "下班前", "今日完成工作", "明日计划",
)


def _query_core_keywords(query: str) -> list[str]:
    return [kw for kw in _DOMAIN_KEYWORDS if kw in query]


def judge_case(case: dict, top_result: dict | None) -> dict:
    """
    LLM-as-judge：用检索片段生成回答 → 评分（相关性/忠实度/完整性）

    规则化 grounding（零 token）恒跑；LLM 评分仅在手动 --judge 时执行。
    """
    from work_agent.agent.llm import get_llm
    from work_agent.core.prompt_manager import prompt_manager

    if not top_result:
        return {"case_id": case.get("id", ""), "skipped": True}

    llm = get_llm()
    chunk = top_result.get("text", "")
    query = case.get("query", "")

    # 1) 生成回答（复用知识回答 Prompt，Prompt 外置铁律）
    answer_prompt = prompt_manager.load("knowledge_answer")["content"].format(
        query=query,
        knowledge=chunk or "（未检索到相关制度）",
        user_context=json.dumps(
            {
                "tenant_id": case.get("tenant_id", ""),
                "department": case.get("department", ""),
            },
            ensure_ascii=False,
        ),
        user_profile="（无，非权限类问题）",
    )
    answer = llm.invoke(answer_prompt).content

    # 2) 规则化 grounding：回答素材（片段）应含 query 核心词，防幻觉/漏检
    core_keywords = _query_core_keywords(query)
    grounding_ok = (
        any(kw in chunk for kw in core_keywords)
        if core_keywords
        else True
    )

    # 3) LLM-as-judge 评分
    judge_prompt = prompt_manager.load("rag_judge")["content"].format(
        query=query,
        chunk=chunk,
        answer=answer,
    )
    raw = llm.invoke(judge_prompt).content
    parsed = safe_parse_json(raw, default={})
    if not isinstance(parsed, dict):
        parsed = {}

    return {
        "case_id": case.get("id", ""),
        "generated_answer": answer,
        "judge_scores": {
            "relevance": parsed.get("relevance"),
            "faithfulness": parsed.get("faithfulness"),
            "completeness": parsed.get("completeness"),
        },
        "reason": parsed.get("reason", ""),
        "grounding_ok": grounding_ok,
    }


def judge_cases(
        cases: list[dict],
        results: list[dict],
        tenant_a: str,
        tenant_b: str,
) -> list[dict]:
    """
    对每个含期望文档的 case，取 top-1 片段做响应质量评估
    """
    by_id = {r["case_id"]: r for r in results}
    out = []
    for case in cases:
        if not case.get("expected_documents"):
            continue
        case_result = by_id.get(case.get("id", ""), {})
        top = (
            case_result.get("results", [{}])[0]
            if case_result.get("results")
            else None
        )
        out.append(judge_case(case, top))
    return out


# ======================
# 报告
# ======================

def generate_report(
        results: list[dict],
        metrics: dict,
        sweep: list[dict] | None = None,
        response_quality: list[dict] | None = None,
        top_k: int = 5,
        output_path: str | None = None,
) -> dict:
    """
    生成评测报告（仿 agent/evaluation/report.py 风格 + 明细/sweep/质量分）
    """
    path = Path(output_path or DEFAULT_REPORT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "suite": "rag_evaluation",
        "top_k": top_k,
        "total_cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "metrics": metrics,
        "cases": results,
        "top_k_sweep": sweep or [],
    }
    if response_quality is not None:
        report["response_quality"] = response_quality

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
