from sentence_transformers import SentenceTransformer


class Embedding:


    def __init__(self):

        self.model = SentenceTransformer(
            "BAAI/bge-small-zh-v1.5"
        )


    @property
    def dimension(self):

        return self.model.get_sentence_embedding_dimension()



    def encode(
            self,
            texts
    ):

        return self.model.encode(
            texts,
            normalize_embeddings=True
        )