from work_agent.core.utils import build_tenant_filter
from work_agent.rag.embedding import Embedding
from work_agent.rag.milvus_store import MilvusVectorStore
from work_agent.rag.retriever import Retriever
from work_agent.rag.permission import PermissionFilter
from work_agent.rag.knowledge import KnowledgeManager

class RAGService:


    def __init__(self):

        self.embedding = Embedding()

        self.store = MilvusVectorStore()

        self.store.create_collection(
            dimension=self.embedding.dimension
        )


        self.retriever = Retriever(
            self.store,
            self.embedding
        )


        self.permission = PermissionFilter()



    def import_knowledge(
            self,
            path="knowledge"
    ):

        """
        导入知识库种子文档
        """

        KnowledgeManager(
            self.store,
            self.embedding
        ).import_knowledge(
            path
        )



    def search(
            self,
            query,
            top_k=5,
            user_context=None
    ):

        """
        检索（仅返回过滤后的结果）
        """

        return self.search_with_meta(
            query,
            top_k,
            user_context
        )["results"]


    def search_with_meta(
            self,
            query,
            top_k=5,
            user_context=None
    ):

        """
        检索并返回元信息

        user_context 形如：
        {
            "tenant_id": "1",
            "department": "财务部",
            "role": "员工"
        }

        返回：
        {
            "results": [...],      # 权限过滤后的结果
            "candidates": N,       # 租户过滤后的候选条数
            "denied": bool         # 存在候选但被权限过滤 → True
        }

        租户隔离在 Milvus 层过滤（预过滤）
        部门/角色权限在 Python 层过滤（PermissionFilter）
        """

        # ======================
        # 租户过滤：企业A员工不能检索企业B文档
        # ======================

        filter_expr = ""

        if user_context:

            tenant_id = (
                user_context.get(
                    "tenant_id",
                    ""
                )
                or ""
            )

            # 空租户文档全局可见 + 用户自己租户（单企业一套知识库，权限靠文档级 access）
            filter_expr = build_tenant_filter(
                tenant_id
            )


        candidates = self.retriever.search(
            query,
            top_k,
            filter=filter_expr
        )


        results = self.permission.filter(
            candidates,
            user_context
        )


        # denied：存在候选且部分被权限过滤（含"全部被过滤"）。
        # 与文档注释"存在候选但被权限过滤 → True"一致；旧实现 len(results)==0
        # 仅识别"全部被过滤"，漏掉"部分内容被拒"（如查询命中受限文档+公开文档）。
        denied = (
            len(candidates) > 0
            and len(results) < len(candidates)
        )

        return {
            "results": results,
            "candidates": len(candidates),
            "denied": denied
        }