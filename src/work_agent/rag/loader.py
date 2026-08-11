from pathlib import Path
import yaml


BASE_DIR = Path(__file__).resolve().parent


def parse_markdown_metadata(content: str):
    """
    解析markdown头部metadata
    """

    metadata = {}


    if content.startswith("---"):

        parts = content.split(
            "---",
            2
        )


        if len(parts) >= 3:

            yaml_content = parts[1]

            metadata = yaml.safe_load(
                yaml_content
            )

            content = parts[2]


    return metadata, content



def load_documents(knowledge_path: str):
    """
    加载知识库文档
    """

    documents = []


    path = Path(knowledge_path)


    for file in path.glob("*.md"):


        raw_content = file.read_text(
            encoding="utf-8"
        )


        metadata, content = parse_markdown_metadata(
            raw_content
        )


        documents.append(
            {
                "filename": file.name,

                "content": content,

                "metadata": metadata
            }
        )


    return documents