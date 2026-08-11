from work_agent.risk.rules import HIGH_RISK_RULES



def check_risk_rule(
        message:str
):


    for keyword,reason in HIGH_RISK_RULES.items():


        if keyword in message:


            return {


                "risk_level":
                    "high",


                "risk_reason":
                    f"命中风险规则：{reason}"

            }


    return None