from work_agent.agent.state import AgentState
from work_agent.agent.llm import get_llm
from work_agent.prompts.loader import load_prompt
from work_agent.core.container import rag_service


import json



def analyze_message_node(state)-> dict:

    message = state["message"]

    template = load_prompt(
        "task_analysis"
    )

    prompt = template.format(
        message=message
    )

    # 创建LLM实例
    llm = get_llm()

    # 调用模型
    result = llm.invoke(prompt)


    print("LLM任务分析结果:")
    print(result.content)


    data = json.loads(
        result.content
    )

    return {

        "task_type":
            data["task_type"],

        "task_status":
            data["task_status"],

        "intent":
            data["intent"],

        "knowledge_category":
            data["knowledge_category"]

    }



def risk_check_node(state):

    message = state.get(
        "message",
        ""
    )


    # ======================
    # 第一层：高危事件硬规则
    # ======================

    high_risk_keywords = [
        "安全事故",
        "生产事故",
        "人身伤害",
        "重大投诉",
        "财务异常"
    ]


    for keyword in high_risk_keywords:

        if keyword in message:

            return {

                "risk_level":
                    "high",

                "risk_reason":
                    f"命中风险规则：{keyword}风险"

            }


    # ======================
    # 第二层：LLM判断
    # ======================


    template = load_prompt(
        "risk_analysis"
    )


    prompt = template.format(
        user=state.get("user",""),
        department=state.get("department",""),
        role=state.get("role",""),
        task_type=state.get("task_type",""),
        task_status=state.get("task_status",""),
        intent=state.get("intent","")
    )


    llm=get_llm()


    result=llm.invoke(
        prompt
    )


    data=json.loads(
        result.content
    )


    return {

        "risk_level":
            data["risk_level"],

        "risk_reason":
            data["risk_reason"]

    }



def retrieve_node(state: AgentState)-> dict:


    print(
        "retrieve收到:",
        state
    )


    meta = rag_service.search_with_meta(
        query=state["message"],

        user_context={
            "tenant_id":
                state.get("tenant_id"),

            "user_id":
                state.get("user_id"),

            "department":
                state.get("department"),

            "role":
                state.get("role")
        }
    )

    results = meta["results"]

    # 存在候选文档但被权限过滤 → 记录权限拒绝（供审计）
    permission_denied = meta["denied"]


    knowledge = "\n".join(
        [
            item["text"]
            for item in results
        ]
    )


    sources=[]


    for item in results:

        metadata=item.get(
            "metadata",
            {}
        )


        sources.append(
            {
                "id":
                    metadata.get("id"),

                "title":
                    metadata.get("title"),

                "version":
                    metadata.get("version"),

                "source":
                    item.get("source"),

                "score":
                    item.get("score")
            }
        )


    print(
        "过滤后知识:",
        knowledge
    )


    return {

        "knowledge":
            knowledge,

        "knowledge_sources":
            sources,

        "permission_denied":
            permission_denied

    }




def response_node(state: AgentState)-> dict:


    template = load_prompt(
        "response"
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


        message=state.get(
            "message",
            ""
        ),


        task_status=state.get(
            "task_status",
            ""
        ),


        risk_level=state.get(
            "risk_level",
            ""
        ),

        supervision_result=state.get(
            "task_supervision_result",
            ""
        ),

        notify_result=state.get(
            "notify_result",
            ""
        ),

        knowledge=state.get(
            "knowledge",
            ""
        ),




        knowledge_sources=
            json.dumps(
                state.get(
                    "knowledge_sources",
                    []
                ),
                ensure_ascii=False
            )
    )


    llm=get_llm()


    result=llm.invoke(
        prompt
    )

    return {

        "response":
            result.content

    }