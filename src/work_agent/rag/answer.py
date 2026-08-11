class RAGAnswer:


    def __init__(
            self,
            llm
    ):

        self.llm = llm



    def generate(
            self,
            query,
            documents
    ):


        context = "\n\n".join(
            [
                doc["text"]
                for doc in documents
            ]
        )


        prompt = f"""
你是企业知识助手。

请严格根据下面知识回答问题。

如果知识中没有答案，
请明确告诉用户不知道。

知识：

{context}


用户问题：

{query}


请给出简洁准确的回答。
"""


        response = self.llm.invoke(
            prompt
        )


        return response.content