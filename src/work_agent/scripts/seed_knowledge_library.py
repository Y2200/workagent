"""
将 knowledge/ 种子知识文档注册进知识库（DB + MinIO + Milvus）

迁移策略：
    现有 Milvus 可能残留无 document_id 的旧孤儿 chunk。
    --reset 会先按 source 文件名手术式删除旧孤儿，再重新导入；
    默认运行只导入缺失的文档，已存在则跳过，防止重复。

用法：
    python -m work_agent.scripts.seed_knowledge_library
    python -m work_agent.scripts.seed_knowledge_library --reset
"""

import argparse
import time

from pathlib import Path

from work_agent.config import settings
from work_agent.core.container import document_service, rag_service
from work_agent.db.session import SessionLocal
from work_agent.document.parser import parse_document
from work_agent.repositories.document_repository import DocumentRepository


SEED_DIR = Path(
    settings.knowledge_path
)


def _reset_orphans() -> None:

    """
    按 source 文件名删除 Milvus 中无 document_id 的旧种子 chunk

    不影响用户后续上传的文档（它们带 document_id）
    """

    filenames = [
        path.name
        for path in SEED_DIR.glob("*.md")
    ]

    if not filenames:
        return

    # 只清理没有 document_id 的旧孤儿 chunk
    # （已走管线的文档带 document_id，不受影响）
    expression = (
        "source in ["
        + ",".join(
            f'"{name}"'
            for name in filenames
        )
        + "] and not exists(document_id)"
    )

    store = rag_service.store

    try:

        result = store.client.delete(
            collection_name=store.COLLECTION_NAME,
            filter=expression
        )

        print(
            f"清理旧孤儿 chunk: {result}"
        )

    except Exception as exc:

        print(
            f"清理旧孤儿 chunk 失败（可忽略）: {exc}"
        )


def _wait_ready(
        document_id: int,
        timeout: float = 120.0
) -> None:

    """
    等待异步管线完成
    """

    repository = DocumentRepository()

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            # expire_all 清除身份映射缓存，确保读到最新状态
            db.expire_all()

            document = repository.get_by_id(
                db,
                document_id
            )

            if document and document.status in (
                    "ready",
                    "failed"
            ):

                print(
                    f"  → {document.filename}: {document.status}"
                )

                return

            time.sleep(1)

        print(
            f"  → 文档 {document_id} 处理超时"
        )

    finally:

        db.close()


def _import_documents() -> None:

    db = SessionLocal()

    try:

        repository = DocumentRepository()

        existing = {
            document.filename
            for document in repository.list(
                db,
                tenant_id=settings.tenant_id,
                limit=1000
            )
        }

    finally:

        db.close()

    for path in sorted(SEED_DIR.glob("*.md")):

        if path.name in existing:

            print(
                f"跳过（已存在）: {path.name}"
            )

            continue

        data = path.read_bytes()

        parsed = parse_document(
            path.name,
            data
        )

        access = (
            parsed.metadata.get(
                "access",
                {}
            )
            or {}
        )

        departments = [
            str(item)
            for item in (
                access.get(
                    "departments",
                    []
                )
                or []
            )
        ]

        roles = [
            str(item)
            for item in (
                access.get(
                    "roles",
                    []
                )
                or []
            )
        ]

        visibility_list = [
            str(item)
            for item in (
                access.get(
                    "visibility",
                    []
                )
                or []
            )
        ]

        is_public = (
            "ALL" in departments
            or "ALL" in visibility_list
        )

        category = str(
            parsed.metadata.get(
                "category",
                ""
            )
            or ""
        )

        document = document_service.upload(
            filename=path.name,
            data=data,
            category=category,
            uploader="system",
            tenant_id=settings.tenant_id,
            visibility=(
                "public"
                if is_public
                else "restricted"
            ),
            departments=departments,
            roles=roles
        )

        print(
            f"已导入: {path.name} (id={document.id})"
        )

        _wait_ready(
            document.id
        )


def main():

    parser = argparse.ArgumentParser(
        description="种子知识库导入"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="先清理旧孤儿 chunk 再重导"
    )

    args = parser.parse_args()

    if args.reset:
        _reset_orphans()

    _import_documents()

    print("种子知识库导入完成")


if __name__ == "__main__":

    main()
