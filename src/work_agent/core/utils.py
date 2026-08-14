import json
import re


def parse_json(text):

    text = text.replace(
        "```json",
        ""
    )

    text = text.replace(
        "```",
        ""
    )

    return json.loads(
        text.strip()
    )


def _extract_json_object(text: str) -> str | None:

    """
    从文本中平衡提取首个 {...} JSON 对象（容忍前后散文/换行）
    """

    start = text.find("{")

    if start == -1:

        return None

    depth = 0

    in_string = False

    for i in range(start, len(text)):

        ch = text[i]

        if ch == '"' and text[i - 1] != "\\":

            in_string = not in_string

        if in_string:

            continue

        if ch == "{":

            depth += 1

        elif ch == "}":

            depth -= 1

            if depth == 0:

                return text[start:i + 1]

    return None


def safe_parse_json(text, default=None):

    """
    容错 JSON 解析（防 LLM 非严格输出导致流程崩溃）

    顺序：剥围栏 json.loads → 平衡提取首个 {...} → 失败返回 default
    """

    if not text or not text.strip():

        return default

    try:

        return parse_json(text)

    except Exception:

        pass

    obj = _extract_json_object(text)

    if obj is not None:

        try:

            return json.loads(obj)

        except Exception:

            pass

    return default


# 问候语（闲聊）词表：命中且无业务关键词 → 直接友好回复，不进督导/知识流
_GREETINGS = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "在吗",
    "在不在",
    "谢谢",
    "谢谢你",
    "再见",
    "拜拜",
)

# 业务关键词：消息含这些时即使带问候词也不算闲聊（避免误伤正常查询）
_BUSINESS_KEYWORDS = (
    "制度",
    "政策",
    "流程",
    "任务",
    "进度",
    "报销",
    "请假",
    "审批",
    "文档",
    "风险",
    "审计",
    "是什么",
    "怎么做",
    "如何",
    "查询",
    "提交",
    "确认",
    "取消",
    "完成",
    "删除",
    "上传",
)


def is_greeting(text) -> bool:

    """
    确定性问候/闲聊判断：短消息 + 命中问候词 + 无业务关键词
    """

    msg = (
        text or ""
    ).strip().lower()

    if not msg or len(msg) > 12:

        return False

    if any(
        keyword in msg
        for keyword in _BUSINESS_KEYWORDS
    ):

        return False

    return any(
        greeting in msg
        for greeting in _GREETINGS
    )
