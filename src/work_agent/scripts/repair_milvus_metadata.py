"""
修复 Milvus chunk metadata（tenant_id + access）与 Postgres 一致

场景：文档在 Phase 1（多租户/权限功能前）入库，Milvus metadata 里
      tenant_id 为空/过期 → 生产按租户预过滤时 0 命中、检索不到。

用法：
    python -m work_agent.scripts.repair_milvus_metadata              # 全部文档
    python -m work_agent.scripts.repair_milvus_metadata --document-id 1
"""

import argparse

from work_agent.db.models import Document
from work_agent.db.session import SessionLocal
from work_agent.knowledge.access import build_access_from_permission_rows
from work_agent.rag.milvus_store import MilvusVectorStore
from work_agent.repositories.document_permission_repository import (
    DocumentPermissionRepository,
)


def repair(
        document_id: int | None = None
) -> None:

    store = MilvusVectorStore()

    db = SessionLocal()

    perm_repo = DocumentPermissionRepository()

    try:

        query = db.query(Document)

        if document_id:

            query = query.filter(
                Document.id == document_id
            )

        documents = (
            query.order_by(Document.id)
            .all()
        )

        if not documents:

            print("没有文档需要修复")

            return

        for doc in documents:

            permissions = perm_repo.get_by_document(
                db,
                doc.id,
            )

            access = build_access_from_permission_rows(
                permissions
            )

            count = store.update_document_metadata(
                doc.id,
                tenant_id=doc.tenant_id,
                access=access,
            )

            print(
                f"document_id={doc.id} "
                f"filename={doc.filename} "
                f"tenant={doc.tenant_id!r} "
                f"milvus_chunks={count}"
            )

    finally:

        db.close()


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="修复 Milvus metadata 与 Postgres 一致"
    )

    parser.add_argument(
        "--document-id",
        type=int,
        default=None,
        help="仅修复指定文档（默认全部）",
    )

    args = parser.parse_args()

    repair(args.document_id)
