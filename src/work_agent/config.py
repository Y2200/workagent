import sys

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Windows 控制台/管道默认 GBK 编码，print 非 GBK 字符（如 ✅、生僻字）会抛
# UnicodeEncodeError。统一重配置为 UTF-8，任何导入本包的脚本自动生效。
if hasattr(sys.stdout, "reconfigure"):

    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

if hasattr(sys.stderr, "reconfigure"):

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):

    """
    系统配置
    """


    # ======================
    # 企业微信（WeCom）
    # ======================

    wechat_corp_id: str = ""

    wechat_secret: str = ""

    wechat_token: str = ""

    wechat_agent_id: str = ""

    # 接收消息安全模式 EncodingAESKey（43 字符）；为空则回调验签/解密不可用
    wechat_encoding_aes_key: str = ""

    # 首次收到未绑定用户消息时是否自动建号（默认关；身份可信但租户归属需配置）
    wechat_auto_create_user: bool = False

    # 自动建号用户归属租户
    wechat_default_tenant_id: str = ""

    # ======================
    # 大模型
    # ======================

    doubao_api_key: str = ""

    model_name: str = "doubao"

    model_base_url: str = ""

    model_temperature: float = 0.2



    # ======================
    # Redis
    # ======================

    redis_url: str = (
        "redis://localhost:6379/0"
    )


    # ======================
    # Milvus（P6-1）
    # pydantic-settings 自动读取环境变量 MILVUS_URI（大小写不敏感，同 redis_url 机制）
    # 默认 localhost 兼容开发；生产 Docker 经 .env 覆盖为内部服务名
    # 例：MILVUS_URI=milvus-standalone:19530
    # ======================

    milvus_uri: str = (
        "http://localhost:19530"
    )


    # ======================
    # RAG
    # ======================

    knowledge_path: str = str(
        BASE_DIR / "knowledge"
    )


    vector_path: str = str(
        BASE_DIR / "data" / "faiss"
    )


    # ======================
    # PostgreSQL
    # ======================

    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/work_agent"
    )


    # ======================
    # MinIO 文档存储
    # 生产必须通过 .env 提供，禁止依赖默认值
    # ======================

    minio_endpoint: str = "localhost:9002"

    minio_access_key: str = ""

    minio_secret_key: str = ""

    minio_bucket: str = "work-documents"

    minio_secure: bool = False


    # ======================
    # JWT 认证
    # 生产必须通过 .env 提供强随机密钥
    # ======================

    jwt_secret: str = ""

    jwt_algorithm: str = "HS256"

    jwt_expire_minutes: int = 1440


    # ======================
    # 初始管理员
    # 生产必须通过 .env 设置强口令
    # ======================

    admin_username: str = "admin"

    admin_password: str = ""


    # ======================
    # 租户（单租户占位，默认空）
    # ======================

    tenant_id: str = ""


    # ======================
    # 成本估算（元 / 1K tokens）
    # ======================

    model_cost_per_1k_tokens: float = 0.001


    # ======================
    # 审计日志保留天数
    # ======================

    audit_log_retention_days: int = 180


    # ======================
    # CORS（P6-1）
    # 逗号分隔的允许来源；留空 = 开发宽松放行（*）
    # 生产填 https://wkcp.online
    # ======================

    cors_origins: str = ""


    # ======================
    # Prompt 管理
    # ======================

    # 默认指向 src/work_agent/prompts
    prompt_path: str = str(
        Path(__file__).resolve().parent / "prompts"
    )

    prompt_cache_enabled: bool = True


    # ======================
    # Agent 版本（审计记录）
    # ======================

    agent_version: str = "0.1.0"


    # ======================
    # 知识智能（P5-4）
    # ======================

    # 文档入库时是否自动分类（关闭则沿用人工类别）
    knowledge_auto_classify: bool = True

    # 知识图谱单文档实体抽取上限
    kg_entity_limit: int = 20


    # ======================
    # 故障恢复（P5-5-5）
    # ======================

    # LLM 瞬时错误最大重试次数
    llm_max_retries: int = 1

    # 熔断器：连续失败阈值 / 冷却秒数
    llm_breaker_failure_threshold: int = 5

    llm_breaker_cooldown_seconds: float = 60.0


    # ======================
    # 日志
    # ======================

    log_path: str = str(
        BASE_DIR / "logs"
    )


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


settings = Settings()