import faiss
import numpy as np
import pickle
from pathlib import Path


class VectorStore:
    """
    FAISS向量数据库
    """


    def __init__(self):

        self.index = None

        self.documents = []

    def build(
            self,
            vectors,
            documents
    ):

        vectors = np.array(
            vectors
        ).astype(
            "float32"
        )

        dimension = vectors.shape[1]

        self.index = faiss.IndexFlatIP(
            dimension
        )

        assert self.index is not None

        self.index.add(
            vectors
        )

        self.documents = documents



    def from_documents(
            self,
            documents: list[dict],
            embedding_model
    ):
        """
        根据文档创建向量库
        """


        texts = [
            doc["text"]
            for doc in documents
        ]


        vectors = embedding_model.encode(
            texts
        )


        self.build(
            vectors,
            documents
        )



    def search(
            self,
            query_vector,
            top_k: int = 5,
            score_threshold: float = 0.4,
            metadata_filter: dict | None = None
    ):
        """
        相似度搜索

        返回:

        [
            {
                text,
                source,
                metadata,
                score
            }
        ]

        """


        top_k = min(
            top_k,
            len(self.documents)
        )


        query_vector = np.array(
            [
                query_vector
            ]
        ).astype(
            "float32"
        )


        scores, indexes = self.index.search(
            query_vector,
            top_k
        )


        results = []


        for score, idx in zip(
                scores[0],
                indexes[0]
        ):

            idx = int(idx)


            # 相似度过滤

            if score < score_threshold:
                continue


            doc = self.documents[idx].copy()



            # metadata权限过滤

            if not self.match_metadata(
                    doc.get(
                        "metadata",
                        {}
                    ),
                    metadata_filter
            ):
                continue



            doc["score"] = float(score)


            results.append(
                doc
            )


        return results

    @staticmethod
    def match_metadata(
            metadata: dict,
            metadata_filter: dict | None
    ):
        """
        判断文档是否允许当前用户访问
        """


        # 没有权限条件
        # 默认全部返回

        if not metadata_filter:
            return True



        department = metadata_filter.get(
            "department"
        )


        role = metadata_filter.get(
            "role"
        )



        access = metadata.get(
            "access",
            {}
        )



        departments = access.get(
            "departments",
            []
        )


        roles = access.get(
            "roles",
            []
        )



        # 部门权限判断

        if department:

            if (
                    "ALL" not in departments
                    and
                    department not in departments
            ):
                return False



        # 角色权限判断

        if role:

            if (
                    role not in roles
                    and
                    "员工" not in roles
                    and
                    "管理人员" not in roles
            ):
                return False



        return True




    def save(
            self,
            path: str
    ):
        """
        保存FAISS索引
        """


        path = Path(path)


        path.mkdir(
            parents=True,
            exist_ok=True
        )


        faiss.write_index(
            self.index,
            str(
                path / "index.faiss"
            )
        )


        with open(
                path / "documents.pkl",
                "wb"
        ) as f:

            pickle.dump(
                self.documents,
                f
            )



    def load(
            self,
            path: str
    ):
        """
        加载FAISS索引
        """


        path = Path(path)


        self.index = faiss.read_index(
            str(
                path / "index.faiss"
            )
        )


        with open(
                path / "documents.pkl",
                "rb"
        ) as f:

            self.documents = pickle.load(
                f
            )