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

    # LLM（GLM via OpenAI 兼容协议）
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4-flash"
    glm_embedding_model: str = "embedding-3"

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
