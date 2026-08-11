class TenantAccessDenied(Exception):

    """
    跨租户越权访问

    Service 层抛出，API 层统一转为 403
    """

    def __init__(
            self,
            message: str = "无权访问该文档"
    ):

        super().__init__(message)


class PromptError(Exception):

    """
    Prompt 管理基类异常
    """

    pass


class PromptNotFoundError(PromptError):

    """
    Prompt 文件不存在
    """

    def __init__(
            self,
            name: str
    ):

        super().__init__(
            f"Prompt 不存在: {name}"
        )

        self.name = name


class PromptVersionError(PromptError):

    """
    Prompt 版本元数据异常（未注册 / 版本缺失）
    """

    def __init__(
            self,
            message: str
    ):

        super().__init__(message)
