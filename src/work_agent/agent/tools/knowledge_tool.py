from work_agent.agent.tools.base import BaseTool


class KnowledgeTool(BaseTool):

    """
    知识检索工具

    内部经 KnowledgeService / RAGService 检索
    禁止直接访问 DB / Milvus
    """

    name = "knowledge_tool"

    description = "检索企业知识库，返回相关制度内容"

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string"
            },
            "top_k": {
                "type": "integer"
            },
        },
        "required": ["query"],
    }


    def execute(
            self,
            *,
            query: str,
            user_context: dict | None = None,
            top_k: int = 5
    ) -> dict:

        # 延迟导入，避免模块加载循环依赖
        from work_agent.core.container import rag_service

        meta = rag_service.search_with_meta(
            query,
            top_k=top_k,
            user_context=user_context,
        )

        return {
            "results": meta["results"],
            "denied": meta["denied"],
            "candidates": meta["candidates"],
        }
