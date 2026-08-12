import json
import re

from work_agent.core.prompt_manager import prompt_manager


class DocumentClassifier:

    """
    文档自动分类

    通过 LLM 判断文档所属知识类别。
    任何失败（LLM 异常 / 输出非 JSON / 内容过短）都回退到 fallback，
    不阻塞文档入库管线。
    """

    def __init__(self, llm=None):

        self.llm = llm


    def classify(
            self,
            *,
            title: str,
            content: str,
            fallback: str = ""
    ) -> str:

        """
        返回分类类别

        fallback 为空时兜底为"未分类"
        """

        if not content or len(content) < 20:

            return fallback or "未分类"

        try:

            loaded = prompt_manager.load(
                "doc_classifier"
            )

            prompt = loaded["content"].format(
                title=title or "",
                content=content[:4000],
            )

            llm = self._get_llm()

            response = llm.invoke(
                prompt
            )

            category = self._parse_category(
                response.content
            )

            return category or fallback or "未分类"

        except Exception:

            # 分类失败绝不阻塞入库
            return fallback or "未分类"


    @staticmethod
    def _parse_category(text: str) -> str:

        """
        从 LLM 输出中解析类别

        兼容纯 JSON 或夹杂说明文字的输出
        """

        if not text:
            return ""

        json_match = re.search(
            r"\{.*\}",
            text,
            re.DOTALL,
        )

        if not json_match:
            return text.strip()[:32]

        try:

            data = json.loads(
                json_match.group(0)
            )

            category = (
                data.get("category")
                or data.get("name")
                or ""
            )

            return str(category).strip()[:64]

        except json.JSONDecodeError:

            return text.strip()[:32]


    def _get_llm(self):

        if self.llm:
            return self.llm

        # 延迟导入，避免容器初始化循环依赖
        from work_agent.agent.llm import get_llm

        self.llm = get_llm()

        return self.llm
