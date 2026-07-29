from functools import lru_cache
from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 数据库
    database_url: str
    test_database_url: str = ""

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Cookie
    cookie_domain: str = "localhost"
    cookie_secure: bool = False

    # 加密
    encryption_key: str

    # LLM chat（GLM via OpenAI 兼容协议，env 兜底用；主配置走 admin 全局/用户自配）
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4.7"

    # Embedding（统一走 bge-m3 微服务，OpenAI 兼容协议；用户/admin 不可配）
    # 部署时启动一个暴露 /embeddings 的服务（Infinity 等），在此填地址即可。
    # 注意：Infinity 端点是 /embeddings（无 /v1 前缀），故 base_url 不带 /v1；
    # langchain openai SDK 会自动在 base_url 后拼 /embeddings。
    # 本地服务通常不校验 api_key，留空。
    embedding_base_url: str = "http://localhost:7997"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str = ""

    # Firecrawl (web ingestion;全局 key 存 SystemSetting,env 仅兜底)
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_enabled: bool = False

    # MinerU（PDF→Markdown 云端解析;全局 token 存 SystemSetting,env 仅兜底）
    # 未配置时 PDF 解析降级到 pypdf 纯文本提取。
    mineru_api_token: str = ""
    mineru_base_url: str = "https://mineru.net"
    mineru_model_version: str = "vlm"  # vlm（高精度）/ pipeline（快）

    # 文件上传（设计 13.2，附录 B：MVP 本地存储）
    upload_dir: str = "uploads"
    max_image_size_mb: int = 10

    # 对象存储（minio，S3 兼容；一刀切，不留 local 分支，见计划关键约束 5）
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "tiangong"
    minio_secret_key: str = "tiangong12345"
    minio_bucket_personal: str = "tiangong-personal"
    minio_bucket_global: str = "tiangong-global"
    minio_secure: bool = False

    # CORS（环境变量中以逗号分隔，按 CSV 解析）
    # NoDecode 阻止 pydantic-settings 把字符串当 JSON 解析，交给下面的 validator 切分
    cors_origins: Annotated[List[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """支持逗号分隔的字符串（如 .env / 环境变量）和已有列表两种输入。"""
        if isinstance(v, str):
            items = [item.strip() for item in v.split(",")]
            return [item for item in items if item]
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        # pydantic-settings 自动从 .env 与环境变量读取
        return cls()  # type: ignore[call-arg]


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
