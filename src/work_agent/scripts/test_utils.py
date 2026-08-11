"""
测试共享工具
"""


def cleanup_tenant_data(
        tenant_ids: tuple[str, ...] = ("1", "2")
) -> int:

    """
    清理租户测试数据（DB 文档 + Milvus 孤儿向量）

    防止历史中断运行留下的孤儿向量污染基线
    """

    from work_agent.core.container import document_service, rag_service
    from work_agent.db.models import Document
    from work_agent.db.session import SessionLocal

    # 1. 删除 DB 文档（连带 Milvus 向量）
    db = SessionLocal()

    try:

        docs = db.query(Document).filter(
            Document.tenant_id.in_(list(tenant_ids))
        ).all()

        for doc in docs:
            document_service.delete(
                doc.id,
                tenant_id=doc.tenant_id,
            )

    finally:

        db.close()

    # 2. 清理 Milvus 孤儿向量（无 DB 记录的残留）
    store = rag_service.store

    expression = (
        'metadata["tenant_id"] in ['
        + ",".join(
            f'"{tid}"'
            for tid in tenant_ids
        )
        + "]"
    )

    result = store.client.query(
        collection_name=store.COLLECTION_NAME,
        filter=expression,
        output_fields=["id"],
        limit=16384,
        consistency_level="Strong",
    )

    ids = [
        row["id"]
        for row in result
    ]

    if ids:

        store.client.delete(
            collection_name=store.COLLECTION_NAME,
            ids=ids,
            consistency_level="Strong",
        )

        store.client.flush(
            store.COLLECTION_NAME
        )

    return len(ids)
