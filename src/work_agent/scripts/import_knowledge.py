from work_agent.rag.service import RAGService


rag = RAGService()


rag.import_knowledge(
    "knowledge"
)


print("知识库导入完成")