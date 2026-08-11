from work_agent.agent.state import AgentState



def wechat_notify_node(
        state: AgentState
)->dict:


    action = state.get(
        "supervision_action"
    )


    if action == "none":

        return {

            "notify_result":
                "无需通知"

        }


    if action == "remind_employee":


        print(
            "发送员工提醒:"
        )

        print(
            state.get("user")
        )


    elif action == "notify_manager":


        print(
            "通知直属负责人:"
        )


        print(
            state.get(
                "supervision_target"
            )
        )


    elif action == "escalate":


        print(
            "升级企业负责人"
        )


    return {


        "notify_result":
            "通知执行完成"

    }