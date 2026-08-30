"""
Prompt Manager 测试

场景1：加载 intent_router → 内容正确
场景2：缓存生效
场景3：不存在 Prompt → PromptNotFoundError
场景4：版本读取正常

用法：
    python -m work_agent.scripts.test_prompt_manager
"""

from work_agent.core.exceptions import (
    PromptNotFoundError,
    PromptVersionError,
)
from work_agent.core.prompt_manager import PromptManager


def test():

    # ======================
    # 场景1：加载 intent_router
    # ======================

    manager = PromptManager(
        cache_enabled=False
    )

    result = manager.load("intent_router")

    assert result["name"] == "intent_router", result

    # 版本与 metadata 一致（动态校验，版本 bump 无需改测试）
    from work_agent.prompts.metadata import PROMPT_METADATA

    assert result["version"] == PROMPT_METADATA[
        "intent_router"
    ]["version"], result

    assert "{message}" in result["content"], "内容应含 message 占位符"

    assert "{user_context}" in result["content"], "内容应含 user_context 占位符"

    print(
        f"场景1 ✅ 加载 intent_router 正确 "
        f"(version={result['version']}, len={len(result['content'])})"
    )

    # ======================
    # 场景2：缓存生效
    # ======================

    cached = PromptManager(
        cache_enabled=True
    )

    first = cached.load("intent_router")

    second = cached.load("intent_router")

    assert second is first, "缓存应返回同一对象"

    assert cached._cache["intent_router"]["name"] == "intent_router", "应写入缓存"

    print("场景2 ✅ 缓存生效（二次加载返回同一对象）")

    # ======================
    # 场景3：不存在 Prompt
    # ======================

    try:

        manager.load("not_exist_prompt")

        assert False, "应抛 PromptNotFoundError"

    except PromptNotFoundError:

        print("场景3 ✅ 不存在的 Prompt → PromptNotFoundError")

    # ======================
    # 场景4：版本读取正常 + 未注册异常
    # ======================

    version = manager.get_version("intent_router")

    from work_agent.prompts.metadata import PROMPT_METADATA

    assert version == PROMPT_METADATA[
        "intent_router"
    ]["version"], version

    print(f"场景4a ✅ 版本读取正常: {version}")

    try:

        manager.get_version("unknown_prompt")

        assert False, "应抛 PromptVersionError"

    except PromptVersionError:

        print("场景4b ✅ 未注册 Prompt 版本 → PromptVersionError")

    # 清单
    prompts = manager.list_prompts()

    assert "intent_router" in prompts, prompts

    print(f"场景5 ✅ 清单含 {len(prompts)} 个已注册 Prompt")

    print("Prompt Manager 测试全部通过")


if __name__ == "__main__":

    test()
