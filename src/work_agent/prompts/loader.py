"""
Prompt 加载门面（向后兼容）

旧调用链：业务 → loader → txt
新调用链：业务 → PromptManager → Prompt Registry → txt

load_prompt() 保留原签名（返回 content 字符串），
实际经 PromptManager 加载（含缓存/版本/异常）。
"""

from work_agent.core.prompt_manager import prompt_manager


def load_prompt(name: str) -> str:
    """
    加载 prompt 模板内容（兼容旧接口）
    """

    return prompt_manager.load(
        name
    )["content"]
