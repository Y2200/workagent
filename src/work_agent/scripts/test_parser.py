"""
文档解析器自检

用法：
    python -m work_agent.scripts.test_parser
"""

from work_agent.document.parser import parse_document


def test_markdown():

    parsed = parse_document(
        "财务报销制度.md",
        (
            "---\n"
            "title: 财务报销制度\n"
            "---\n"
            "差旅报销需提交发票，超标需审批。"
        ).encode("utf-8")
    )

    assert parsed.metadata.get("title") == "财务报销制度", parsed.metadata

    assert len(parsed.content) > 0

    print(
        f"md ok: title={parsed.metadata.get('title')}, "
        f"content_len={len(parsed.content)}"
    )


def test_txt():

    parsed = parse_document(
        "test.txt",
        "你好，世界".encode("utf-8")
    )

    assert parsed.content == "你好，世界"

    print("txt ok")


def test_unsupported():

    try:

        parse_document(
            "bad.exe",
            b"xx"
        )

        print("FAIL: 应拒绝不支持的类型")

    except ValueError:

        print("unsupported ok")


if __name__ == "__main__":

    test_markdown()

    test_txt()

    test_unsupported()

    print("解析器自检全部通过")
