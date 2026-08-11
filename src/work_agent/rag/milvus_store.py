from pymilvus import MilvusClient, DataType


class MilvusVectorStore:


    COLLECTION_NAME = "enterprise_knowledge"


    def __init__(self):

        self.client = MilvusClient(
            uri="http://localhost:19530"
        )

    def create_collection(self,dimension=384):

        if self.client.has_collection(
                self.COLLECTION_NAME
        ):
            print("Collection已存在，加载中")

            self.client.load_collection(
                collection_name=self.COLLECTION_NAME
            )

            return

        print("创建Collection")

        schema = self.client.create_schema(
            auto_id=True,
            enable_dynamic_field=True
        )

        schema.add_field(
            field_name="id",
            datatype=DataType.INT64,
            is_primary=True
        )

        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=dimension
        )

        schema.add_field(
            field_name="text",
            datatype=DataType.VARCHAR,
            max_length=65535
        )

        schema.add_field(
            field_name="source",
            datatype=DataType.VARCHAR,
            max_length=512
        )

        schema.add_field(
            field_name="category",
            datatype=DataType.VARCHAR,
            max_length=128
        )

        schema.add_field(
            field_name="metadata",
            datatype=DataType.JSON
        )

        self.client.create_collection(
            collection_name=self.COLLECTION_NAME,
            schema=schema
        )

        index_params = self.client.prepare_index_params()

        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="IP"
        )

        self.client.create_index(
            collection_name=self.COLLECTION_NAME,
            index_params=index_params
        )

        self.client.load_collection(
            collection_name=self.COLLECTION_NAME
        )

    def count(self):

        result = self.client.query(
            collection_name=self.COLLECTION_NAME,
            filter="",
            output_fields=[
                "id"
            ],
            limit=10000
        )

        return len(result)

    def from_documents(
            self,
            documents,
            embedding_model
    ):

        vectors = embedding_model.encode(
            [
                doc["text"]
                for doc in documents
            ]
        )

        data = []

        for doc, vector in zip(
                documents,
                vectors
        ):
            metadata = doc.get(
                "metadata",
                {}
            )

            data.append(
                {
                    "vector":
                        vector.tolist(),

                    "text":
                        doc["text"],

                    "source":
                        doc.get(
                            "source",
                            ""
                        ),

                    "category":
                        metadata.get(
                            "category",
                            ""
                        ),

                    "metadata":
                        metadata
                }
            )

        result = self.client.insert(
            collection_name=self.COLLECTION_NAME,
            data=data
        )

        print(
            f"Milvus插入完成:{result}"
        )

        # 关键
        self.client.flush(
            self.COLLECTION_NAME
        )


    def search(
            self,
            query_vector,
            top_k=5,
            score_threshold = 0.55,
            filter=""
    ):

        """
        filter 为 Milvus 元数据过滤表达式（如租户隔离）
        """

        search_kwargs = {
            "collection_name":
                self.COLLECTION_NAME,

            "data": [
                query_vector.tolist()
            ],

            "anns_field":
                "vector",

            "limit":
                top_k,

            "output_fields": [
                "text",
                "source",
                "category",
                "metadata"
            ],

            "search_params": {
                "metric_type": "IP"
            }
        }

        if filter:
            search_kwargs["filter"] = filter

        result = self.client.search(
            **search_kwargs
        )


        results=[]

        for item in result[0]:

            if item["distance"] < score_threshold:
                continue

            entity = item["entity"]


            results.append(
                {
                    "text":
                        entity["text"],

                    "source":
                        entity["source"],

                    "metadata":
                        entity["metadata"],

                    "score":
                        item["distance"]
                }
            )


        return results


    def insert_documents(
            self,
            documents,
            embedding_model,
            document_id: int,
            category: str = "",
            tenant_id: str = ""
    ) -> list[int]:

        """
        带 document_id 动态字段插入文档切片

        knowledge_chunks 表是事实源，此处返回 milvus 主键 ids
        """

        vectors = embedding_model.encode(
            [
                doc["text"]
                for doc in documents
            ]
        )

        data = []

        for doc, vector in zip(
                documents,
                vectors
        ):

            metadata = dict(
                doc.get(
                    "metadata",
                    {}
                )
            )

            metadata["document_id"] = document_id

            metadata["tenant_id"] = tenant_id

            data.append(
                {
                    "vector":
                        vector.tolist(),

                    "text":
                        doc["text"],

                    "source":
                        doc.get(
                            "source",
                            ""
                        ),

                    "category":
                        category,

                    "metadata":
                        metadata,

                    # 动态字段：用于按文档过滤/删除
                    "document_id":
                        document_id
                }
            )

        result = self.client.insert(
            collection_name=self.COLLECTION_NAME,
            data=data
        )

        # 关键
        self.client.flush(
            self.COLLECTION_NAME
        )

        if isinstance(result, dict):
            return list(
                result.get(
                    "ids",
                    []
                )
            )

        return list(
            result.primary_keys
        )


    def delete_by_ids(
            self,
            ids: list[int]
    ) -> int:

        """
        按 Milvus 主键删除向量

        主删除机制：id 来自 knowledge_chunks.milvus_id
        """

        result = self.client.delete(
            collection_name=self.COLLECTION_NAME,
            ids=list(ids),
            consistency_level="Strong"
        )

        if isinstance(result, dict):
            return result.get(
                "delete_count",
                0
            )

        return 0


    def delete_by_document(
            self,
            document_id: int
    ) -> int:

        """
        按 document_id 动态字段删除（辅助兜底）
        """

        result = self.client.delete(
            collection_name=self.COLLECTION_NAME,
            filter=f"document_id == {document_id}",
            consistency_level="Strong"
        )

        if isinstance(result, dict):
            return result.get(
                "delete_count",
                0
            )

        return 0


    def search_with_document(
            self,
            query_vector,
            top_k=5,
            score_threshold=0.5,
            filter=""
    ):

        """
        检索并返回 document_id

        filter 为 Phase2 权限元数据过滤预留
        """

        search_kwargs = {
            "collection_name":
                self.COLLECTION_NAME,

            "data": [
                query_vector.tolist()
            ],

            "anns_field":
                "vector",

            "limit":
                top_k,

            "output_fields": [
                "text",
                "source",
                "category",
                "metadata"
            ],

            "search_params": {
                "metric_type": "IP"
            },

            "consistency_level":
                "Strong"
        }

        if filter:
            search_kwargs["filter"] = filter

        result = self.client.search(
            **search_kwargs
        )

        results = []

        for item in result[0]:

            if item["distance"] < score_threshold:
                continue

            entity = item["entity"]

            metadata = entity.get(
                "metadata",
                {}
            ) or {}

            results.append(
                {
                    "text":
                        entity.get(
                            "text",
                            ""
                        ),

                    "source":
                        entity.get(
                            "source",
                            ""
                        ),

                    "category":
                        entity.get(
                            "category",
                            ""
                        ),

                    "metadata":
                        metadata,

                    "document_id":
                        metadata.get(
                            "document_id"
                        ),

                    "score":
                        item["distance"]
                }
            )

        return results


    def count_by_document(
            self,
            document_id: int
    ) -> int:

        """
        统计某文档的向量条数
        """

        result = self.client.query(
            collection_name=self.COLLECTION_NAME,
            filter=f"document_id == {document_id}",
            output_fields=[
                "id"
            ],
            limit=16384,
            consistency_level="Strong"
        )

        return len(result)


    def update_document_access(
            self,
            document_id: int,
            access: dict
    ) -> int:

        """
        同步文档的 access 权限元数据到 Milvus

        修改权限后调用，保证 RAG 过滤结果即时生效
        """

        result = self.client.query(
            collection_name=self.COLLECTION_NAME,
            filter=f"document_id == {document_id}",
            output_fields=[
                "id",
                "vector",
                "text",
                "source",
                "category",
                "metadata"
            ],
            limit=16384,
            consistency_level="Strong"
        )

        data = []

        for row in result:

            metadata = dict(
                row.get(
                    "metadata",
                    {}
                )
                or {}
            )

            metadata["access"] = access

            data.append(
                {
                    "id":
                        row["id"],

                    "vector":
                        row["vector"],

                    "text":
                        row.get(
                            "text",
                            ""
                        ),

                    "source":
                        row.get(
                            "source",
                            ""
                        ),

                    "category":
                        row.get(
                            "category",
                            ""
                        ),

                    "metadata":
                        metadata,

                    "document_id":
                        document_id
                }
            )

        if data:

            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                data=data
            )

            self.client.flush(
                self.COLLECTION_NAME
            )

        return len(data)