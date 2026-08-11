"""
Milvus 增量扩展自检

用法：
    python -m work_agent.scripts.test_milvus
"""

from work_agent.core.container import rag_service


def test():

    store = rag_service.store

    embedding = rag_service.embedding

    # 测试用 document_id，避免与真实数据冲突
    document_id = 999999

    chunks = [
        {
            "text": "测试文档内容之一：报销流程",
            "source": "test.md",
            "metadata": {}
        },
        {
            "text": "测试文档内容之二：审批权限",
            "source": "test.md",
            "metadata": {}
        }
    ]

    # insert_documents 返回 milvus ids
    ids = store.insert_documents(
        chunks,
        embedding,
        document_id=document_id,
        category="测试"
    )

    assert len(ids) == 2, f"插入失败: {ids}"

    print(f"insert_documents ok: {ids}")

    assert store.count_by_document(document_id) == 2

    print("count_by_document ok")

    # search_with_document 返回 document_id
    hits = store.search_with_document(
        embedding.encode(
            ["测试文档内容"]
        )[0],
        top_k=5,
        score_threshold=0.0
    )

    assert any(
        hit.get("document_id") == document_id
        for hit in hits
    ), "search 未返回测试 document_id"

    print("search_with_document ok")

    # 主删除机制：按 ids 删
    deleted = store.delete_by_ids(ids)

    assert store.count_by_document(document_id) == 0, "删除不彻底"

    print(f"delete_by_ids ok: {deleted}")

    print("Milvus 扩展自检全部通过")


if __name__ == "__main__":

    test()
