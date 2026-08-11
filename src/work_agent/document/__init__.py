"""
document 模块

负责上传文档的解析与入库管线
"""

from work_agent.document.parser import parse_document
from work_agent.document.pipeline import DocumentPipeline


__all__ = [
    "parse_document",
    "DocumentPipeline"
]
