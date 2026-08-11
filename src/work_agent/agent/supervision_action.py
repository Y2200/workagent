from work_agent.agent.state import AgentState
from work_agent.agent.llm import get_llm
from work_agent.prompts.loader import load_prompt

import json



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


    data=json.loads(
        result.content
    )


    return {

        "supervision_action":
            data["action"],


        "supervision_target":
            data["target"],


        "supervision_channel":
            data["channel"],


        "supervision_priority":
            data["priority"]

    }