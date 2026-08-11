"""
storage 模块

负责 MinIO 对象存储
"""

from work_agent.storage.minio import MinioStorage, build_object_key


__all__ = [
    "MinioStorage",
    "build_object_key"
]
