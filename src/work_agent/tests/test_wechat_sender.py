from work_agent.wechat.sender import send_text_message


result = send_text_message(
    "员工A",
    "测试消息"
)


print(result)