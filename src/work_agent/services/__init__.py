"""
Service 层

负责业务编排，不直接操作数据库表
"""

from work_agent.services.document_service import DocumentService


__all__ = [
    "DocumentService"
]
