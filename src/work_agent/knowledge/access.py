def build_access(
        departments: list[str],
        roles: list[str],
        user_ids: list[int]
) -> dict:

    """
    构建 Milvus chunk metadata 的 access 结构

    无任何限制 → departments=["ALL"] 全员可见
    """

    if not departments and not roles and not user_ids:

        departments = ["ALL"]

    return {
        "departments": departments,
        "roles": roles,
        "user_ids": user_ids,
    }


def build_access_from_permission_rows(
        rows
) -> dict:

    """
    从 document_permission 行构建 access
    """

    departments = sorted({
        row.department
        for row in rows
        if row.department
    })

    roles = sorted({
        row.role
        for row in rows
        if row.role
    })

    user_ids = sorted({
        int(row.user_id)
        for row in rows
        if row.user_id is not None
    })

    return build_access(
        departments,
        roles,
        user_ids,
    )
