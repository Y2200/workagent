from work_agent.agent.state import AgentState



def task_handler_node(
        state: AgentState
):


    task_status = state.get(
        "task_status"
    )


    user = state.get(
        "user"
    )


    if task_status == "未提交":


        response = (
            f"{user}您好，"
            "检测到您的任务尚未提交，"
            "请及时补充提交。"
        )


    elif task_status == "延期":


        response = (
            f"{user}您好，"
            "检测到当前任务存在延期情况，"
            "请确认延期原因并及时处理。"
        )


    else:

        response = (
            f"{user}您好，"
            "已记录您的任务状态。"
        )


    return {

        **state,

        "response":
            response

    }