class Retriever:
    """
    RAG检索器
    """

    def __init__(
            self,
            store,
            embedding
    ):

        self.store = store
        self.embedding = embedding



    def search(
            self,
            query: str,
            top_k=5,
            filter=""
    ):


        vector = self.embedding.encode(
            [
                query
            ]
        )[0]


        results = self.store.search(
            vector,
            top_k=top_k,
            score_threshold=0.55,
            filter=filter
        )


        return results