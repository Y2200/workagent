from work_agent.agent.state import AgentState
from work_agent.agent.llm import get_llm
from work_agent.prompts.loader import load_prompt

import json



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


    data=json.loads(
        result.content
    )


    return {

        "supervision_status":
            data["supervision_status"],


        "task_supervision_result":
            data["supervision_result"],


        "supervision_action":
            data["action"],


        "supervision_target":
            data["target"],


        "supervision_deadline":
            data["deadline"]
    }