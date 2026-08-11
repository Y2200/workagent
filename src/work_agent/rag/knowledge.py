from work_agent.rag.loader import load_documents
from work_agent.rag.splitter import split_documents


class KnowledgeManager:
    """
    知识库管理
    """


    def __init__(
            self,
            store,
            embedding
    ):

        self.store = store

        self.embedding = embedding



    def import_knowledge(
            self,
            path="knowledge"
    ):

        documents = load_documents(
            path
        )


        chunks = split_documents(
            documents
        )


        print(
            f"加载{len(chunks)}个知识片段"
        )


        self.store.from_documents(
            chunks,
            self.embedding
        )


        print(
            "知识库导入完成"
        )