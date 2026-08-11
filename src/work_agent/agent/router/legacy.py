from work_agent.agent.state import AgentState



def router_node(
        state: AgentState
):


    intent = state.get(
        "intent",
        ""
    )


    task_status = state.get(
        "task_status",
        ""
    )


    # 制度查询

    if intent == "制度查询":

        return {

            **state,

            "next_action":
                "retrieve"

        }


    # 任务异常

    if (
        intent == "任务异常"
        or
        task_status in [
            "延期",
            "未提交"
        ]
    ):

        return {

            **state,

            "next_action":
                "task_handler"

        }


    return {

        **state,

        "next_action":
            "retrieve"

    }