def split_documents(
    documents: list[dict],
    chunk_size: int = 500,
    chunk_overlap: int = 100
):
    """
    文档切分

    documents格式:

    [
        {
            "filename": "日报制度.md",
            "content": "...",
            "metadata": {}
        }
    ]

    """


    chunks = []


    for doc in documents:

        text = doc["content"]

        filename = doc["filename"]

        metadata = doc.get(
            "metadata",
            {}
        )


        start = 0


        while start < len(text):

            end = start + chunk_size


            chunk_text = text[start:end]


            chunks.append(
                {
                    "text": chunk_text,

                    "source": filename,

                    "metadata": metadata
                }
            )


            start = end - chunk_overlap


    return chunks