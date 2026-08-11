from langgraph.graph import StateGraph, START, END

from work_agent.agent.state import AgentState

from work_agent.agent.router import router_node

from work_agent.agent.task_handler import task_handler_node

from work_agent.agent.supervision_action import supervision_action_node

from work_agent.agent.supervision import (
    task_supervision_node
)

from work_agent.agent.wechat_notify import (
    wechat_notify_node
)

from work_agent.agent.nodes import (
    analyze_message_node,
    risk_check_node,
    retrieve_node,
    response_node,
)


builder = StateGraph(AgentState)


# 消息分析
builder.add_node(
    "analyze_message",
    analyze_message_node
)


# 风险判断
builder.add_node(
    "risk_check",
    risk_check_node
)


# RAG检索
builder.add_node(
    "retrieve",
    retrieve_node
)


# 任务督导
builder.add_node(
    "task_supervision",
    task_supervision_node
)


builder.add_node(
    "supervision_action",
    supervision_action_node
)


# 回复生成
builder.add_node(
    "response",
    response_node
)


builder.add_node(
    "wechat_notify",
    wechat_notify_node
)

# 后续扩展节点，暂时保留
builder.add_node(
    "router",
    router_node
)


builder.add_node(
    "task_handler",
    task_handler_node
)



# ======================
# 主流程
# ======================

builder.add_edge(
    START,
    "analyze_message"
)


builder.add_edge(
    "analyze_message",
    "risk_check"
)


builder.add_edge(
    "risk_check",
    "retrieve"
)


builder.add_edge(
    "retrieve",
    "task_supervision"
)

builder.add_edge(
    "task_supervision",
    "supervision_action"
)

builder.add_edge(
    "supervision_action",
    "wechat_notify"
)


builder.add_edge(
    "wechat_notify",
    "response"
)

builder.add_edge(
    "response",
    END
)



# ======================
# 任务处理备用流程
# 暂不接入
# ======================

builder.add_edge(
    "task_handler",
    END
)



workflow = builder.compile()