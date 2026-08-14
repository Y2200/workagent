"""
闲聊路由 + 督导 JSON 容错测试

Part 1  is_greeting：问候词命中 / 业务词不误伤 / 长句
Part 2  safe_parse_json：正常 / 空串 / 散文 / markdown / 散文包裹 JSON
Part 3  planner 路由：问候→chat、任务→task、风险→risk、知识→knowledge（原路由不变）
Part 4  supervisor dispatch：kind=chat → 友好回复，不进 legacy
Part 5  supervision_action_node：LLM 空/散文 → 兜底默认不崩溃；markdown JSON → 正常解析

用法：
    python -m work_agent.scripts.test_chat_routing
"""

from work_agent.agent.agents.supervisor import supervisor_agent
from work_agent.agent.context import AgentContext
from work_agent.agent.planner import agent_planner
from work_agent.agent.schemas import IntentResult, IntentType, PlanResult
from work_agent.core.utils import is_greeting, safe_parse_json
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _setup():

    seed_tenants()


def _user(username):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(
            db,
            username,
        )

    finally:

        db.close()


def _context():

    emp = _user("A财务员工")

    assert emp, "需要 A财务员工 测试用户"

    return AgentContext.build(
        user=emp,
        channel="wechat",
    )


def _intent(
        intent: str,
        *,
        confidence: float = 0.9
) -> IntentResult:

    return IntentResult(
        intent=intent,
        confidence=confidence,
    )


# ======================
# Part 1 问候检测
# ======================

def test_is_greeting():

    assert is_greeting("你好") is True

    assert is_greeting("你好啊") is True

    assert is_greeting("早上好") is True

    assert is_greeting("hi") is True

    # 业务词不误伤
    assert is_greeting("报销制度是什么") is False

    assert is_greeting("我的任务") is False

    assert is_greeting("提交财务模块开发 完成50%") is False

    # 长句不误判
    assert is_greeting("你好，帮我查一下报销制度") is False

    assert is_greeting("") is False

    print("Part 1 ✅ is_greeting（问候命中 / 业务词不误伤 / 长句）")


# ======================
# Part 2 容错 JSON 解析
# ======================

def test_safe_parse_json():

    # 正常 JSON
    assert safe_parse_json('{"a": 1}') == {"a": 1}

    # 空串 → default
    assert safe_parse_json("", default={"a": 0}) == {"a": 0}

    # 纯散文 → default
    assert safe_parse_json("好的我明白了", default=None) is None

    # markdown 围栏
    assert safe_parse_json('```json\n{"a": 2}\n```') == {"a": 2}

    # 散文包裹 JSON
    assert safe_parse_json('结果如下 {"b": 3} 结束') == {"b": 3}

    print("Part 2 ✅ safe_parse_json（正常/空串/散文/markdown/包裹）")


# ======================
# Part 3 planner 路由
# ======================

def test_planner_routing():

    context = _context()

    # ① 问候（SMALL_TALK）→ chat
    plan = agent_planner.plan(
        message="你好啊",
        intent_result=_intent(IntentType.SMALL_TALK),
        context=context,
    )

    assert plan.kind == "chat", plan.kind

    # ② 问候但 LLM 判成 UNKNOWN → is_greeting 兜底 → chat
    plan2 = agent_planner.plan(
        message="你好啊",
        intent_result=_intent(IntentType.UNKNOWN, confidence=0.3),
        context=context,
    )

    assert plan2.kind == "chat", plan2.kind

    # ③ 任务 → task（原路由不变）
    plan3 = agent_planner.plan(
        message="我的任务",
        intent_result=_intent(IntentType.TASK_MANAGEMENT),
        context=context,
    )

    assert plan3.kind == "task", plan3.kind

    # ④ 风险 → risk（原路由不变）
    plan4 = agent_planner.plan(
        message="任务延期风险",
        intent_result=_intent(IntentType.RISK_ANALYSIS),
        context=context,
    )

    assert plan4.kind == "risk", plan4.kind

    # ⑤ 知识 → knowledge（原路由不变）
    plan5 = agent_planner.plan(
        message="报销制度是什么",
        intent_result=_intent(IntentType.KNOWLEDGE_QUERY),
        context=context,
    )

    assert plan5.kind == "knowledge", plan5.kind

    assert plan5.steps and plan5.steps[0].tool == "knowledge_tool", plan5

    print("Part 3 ✅ planner 路由（问候→chat；任务/风险/知识原路由不变）")


# ======================
# Part 4 supervisor chat
# ======================

def test_supervisor_chat():

    context = _context()

    plan = PlanResult(
        kind="chat",
        intent=IntentType.SMALL_TALK,
        steps=[],
        reasoning="闲聊/问候",
    )

    result = supervisor_agent.dispatch(
        context=context,
        plan=plan,
        message="你好",
    )

    assert result.agent == "chat", result.agent

    assert "企业智能助手" in result.response, result.response

    assert result.knowledge_sources == [], result

    print("Part 4 ✅ supervisor chat（直接友好回复，不进 legacy）")


# ======================
# Part 5 supervision_action 兜底
# ======================

def test_supervision_node_fallback():

    import work_agent.agent.supervision_action as sa

    class FakeResult:

        def __init__(
                self,
                content
        ):

            self.content = content

    class FakeLLM:

        def __init__(
                self,
                content
        ):

            self._content = content

        def invoke(
                self,
                prompt
        ):

            return FakeResult(
                self._content
            )

    real_get_llm = sa.get_llm

    state = {
        "user": "张三",
        "department": "研发部",
        "role": "员工",
        "task_type": "",
        "risk_level": "",
        "risk_reason": "",
        "task_supervision_result": "",
    }

    try:

        # ① LLM 返回空串 → 兜底默认，不崩溃
        sa.get_llm = lambda: FakeLLM("")

        out = sa.supervision_action_node(state)

        assert out["supervision_action"] == "none", out

        assert out["supervision_channel"] == "wechat", out

        assert out["supervision_priority"] == "low", out

        # ② LLM 返回散文 → 兜底默认
        sa.get_llm = lambda: FakeLLM("好的，我明白了，会跟进处理。")

        out2 = sa.supervision_action_node(state)

        assert out2["supervision_action"] == "none", out2

        # ③ markdown 包裹 JSON → 正常解析
        sa.get_llm = lambda: FakeLLM(
            '```json\n'
            '{"action":"remind_employee","target":"员工本人",'
            '"channel":"wechat","priority":"medium"}\n'
            '```'
        )

        out3 = sa.supervision_action_node(state)

        assert out3["supervision_action"] == "remind_employee", out3

    finally:

        sa.get_llm = real_get_llm

    print("Part 5 ✅ supervision_action 兜底（空/散文→默认；markdown JSON→解析）")


def test():

    _setup()

    test_is_greeting()

    test_safe_parse_json()

    test_planner_routing()

    test_supervisor_chat()

    test_supervision_node_fallback()


if __name__ == "__main__":

    test()
