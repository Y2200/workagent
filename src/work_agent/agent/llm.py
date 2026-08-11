from langchain_openai import ChatOpenAI

from work_agent.config import settings


def get_llm():
    """
    创建LLM实例
    """

    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.doubao_api_key,
        base_url=settings.model_base_url,
        temperature=settings.model_temperature,
    )