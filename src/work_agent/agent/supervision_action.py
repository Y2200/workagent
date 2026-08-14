import logging

from work_agent.agent.state import AgentState
from work_agent.agent.llm import get_llm
from work_agent.core.utils import safe_parse_json
from work_agent.prompts.loader import load_prompt


logger = logging.getLogger(__name__)



def supervision_action_node(
        state: AgentState
)->dict:


    template = load_prompt(
        "supervision_action"
    )


    prompt = template.format(

        user=state.get(
            "user",
            ""
        ),

        department=state.get(
            "department",
            ""
        ),

        role=state.get(
            "role",
            ""
        ),

        task_type=state.get(
            "task_type",
            ""
        ),

        risk_level=state.get(
            "risk_level",
            ""
        ),

        risk_reason=state.get(
            "risk_reason",
            ""
        ),

        task_supervision_result=
            state.get(
                "task_supervision_result",
                ""
            )
    )


    llm=get_llm()


    result=llm.invoke(
        prompt
    )


    content=(
        result.content or ""
    ).strip()


    data=safe_parse_json(
        content,
        default={},
    )


    if not data.get(
        "action"
    ):

        logger.warning(
            "supervision_action 解析失败，回退 none。原始返回: %r",
            content[:200],
        )


    return {

        "supervision_action":
            data.get(
                "action",
                "none"
            ),


        "supervision_target":
            data.get(
                "target",
                ""
            ),


        "supervision_channel":
            data.get(
                "channel",
                "wechat"
            ),


        "supervision_priority":
            data.get(
                "priority",
                "low"
            )

    }