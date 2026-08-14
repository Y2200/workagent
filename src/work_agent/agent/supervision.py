import logging

from work_agent.agent.state import AgentState
from work_agent.agent.llm import get_llm
from work_agent.core.utils import safe_parse_json
from work_agent.prompts.loader import load_prompt


logger = logging.getLogger(__name__)



def task_supervision_node(
        state: AgentState
)->dict:

    if (
            state.get("intent") == "制度查询"
            and state.get("task_status") == "未知"
            and state.get("risk_level") == "low"
            and state.get("knowledge_category") not in [
        "安全管理"
    ]
    ):
        return {
            "supervision_status": "normal",
            "task_supervision_result":
                "普通制度查询，无需任务督导",
            "supervision_action": "none"
        }

    template = load_prompt(
        "task_supervision"
    )


    prompt = template.format(

        user=state.get(
            "user"
        ),

        department=state.get(
            "department"
        ),

        role=state.get(
            "role"
        ),

        task_type=state.get(
            "task_type"
        ),

        task_status=state.get(
            "task_status"
        ),

        risk_level=state.get(
            "risk_level"
        ),

        knowledge=state.get(
            "knowledge"
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
        "supervision_status"
    ):

        logger.warning(
            "task_supervision 解析失败，回退 normal。原始返回: %r",
            content[:200],
        )


    return {

        "supervision_status":
            data.get(
                "supervision_status",
                "normal"
            ),


        "task_supervision_result":
            data.get(
                "supervision_result",
                "任务督导未解析，默认正常"
            ),


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


        "supervision_deadline":
            data.get(
                "deadline",
                ""
            )
    }