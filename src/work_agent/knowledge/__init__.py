"""
knowledge 模块

知识服务门面，对外提供知识检索与知识智能能力
"""

from work_agent.knowledge.service import KnowledgeService
from work_agent.knowledge.classifier import DocumentClassifier
from work_agent.knowledge.graph import KnowledgeGraphService
from work_agent.knowledge.similarity import SimilarDocumentService
from work_agent.knowledge.quality import KnowledgeQualityService


__all__ = [
    "KnowledgeService",
    "DocumentClassifier",
    "KnowledgeGraphService",
    "SimilarDocumentService",
    "KnowledgeQualityService",
]
