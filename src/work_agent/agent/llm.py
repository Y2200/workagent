from langchain_openai import ChatOpenAI

from work_agent.config import settings
from work_agent.core.resilience import ResilientLLM, get_breaker


def get_llm():
    """
    创建 LLM 实例（P5-5-5：带重试 + 熔断的透明包装）

    接口不变（invoke），瞬时错误自动重试，连续失败熔断快速失败，
    上层 Agent 捕获后走确定性回退
    """

    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.doubao_api_key,
        base_url=settings.model_base_url,
        temperature=settings.model_temperature,
    )

    breaker = get_breaker(
        f"llm:{settings.model_name}",
        failure_threshold=settings.llm_breaker_failure_threshold,
        cooldown_seconds=settings.llm_breaker_cooldown_seconds,
    )

    return ResilientLLM(
        llm=llm,
        breaker=breaker,
        max_retries=settings.llm_max_retries,
    )