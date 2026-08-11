import io
import re

from uuid import uuid4

from minio import Minio
from minio.error import S3Error

from work_agent.config import settings


def sanitize_filename(filename: str) -> str:

    """
    清理文件名，移除路径分隔符与控制字符
    """

    name = filename.replace(
        "\\",
        "_"
    ).replace(
        "/",
        "_"
    )

    name = re.sub(
        r"[\x00-\x1f]",
        "",
        name
    )

    return name or "file"


def build_object_key(
        tenant_id: str,
        filename: str
) -> str:

    """
    构造 MinIO 对象 key

    预留租户隔离结构：
    tenants/{tenant_id}/documents/{uuid}_{filename}

    单租户（tenant_id 为空）退化为：
    documents/{uuid}_{filename}
    """

    safe = sanitize_filename(filename)

    obj = f"{uuid4().hex}_{safe}"

    if tenant_id:
        return f"tenants/{tenant_id}/documents/{obj}"

    return f"documents/{obj}"


class MinioStorage:

    """
    MinIO 对象存储
    """

    def __init__(
            self,
            endpoint: str | None = None,
            access_key: str | None = None,
            secret_key: str | None = None,
            bucket: str | None = None,
            secure: bool | None = None
    ):

        self.endpoint = endpoint or settings.minio_endpoint

        self.access_key = access_key or settings.minio_access_key

        self.secret_key = secret_key or settings.minio_secret_key

        self.bucket = bucket or settings.minio_bucket

        self.secure = (
            settings.minio_secure
            if secure is None
            else secure
        )

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure
        )


    def ensure_bucket(self) -> None:

        """
        确保 bucket 存在
        """

        if not self.client.bucket_exists(
                self.bucket
        ):

            self.client.make_bucket(
                self.bucket
            )


    def put_object(
            self,
            object_key: str,
            data: bytes,
            content_type: str = "application/octet-stream"
    ) -> str:

        """
        上传对象，返回对象 key
        """

        self.client.put_object(
            self.bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type
        )

        return object_key


    def get_object_bytes(
            self,
            object_key: str
    ) -> bytes:

        """
        读取对象内容
        """

        response = self.client.get_object(
            self.bucket,
            object_key
        )

        try:
            return response.read()

        finally:
            response.close()
            response.release_conn()


    def remove_object(
            self,
            object_key: str
    ) -> None:

        """
        删除对象（不存在时静默忽略）
        """

        try:
            self.client.remove_object(
                self.bucket,
                object_key
            )

        except S3Error:
            pass


    def object_exists(
            self,
            object_key: str
    ) -> bool:

        """
        判断对象是否存在
        """

        try:
            self.client.stat_object(
                self.bucket,
                object_key
            )

            return True

        except S3Error:
            return False
