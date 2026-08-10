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
    # access 短期有效：过期后前端 401 时静默调用 /auth/refresh 续期，用户无感。
    access_token_expire_minutes: int = 30
    # refresh 长期有效：真正的「记住登录」窗口（30 天），是 access 过期后的兜底。
    refresh_token_expire_days: int = 30

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

    # Rerank（本地 Infinity 微服务跑 bge-reranker-v2-m3，与 embedding 对称）
    # 部署时启动一个暴露 /rerank 的服务（Infinity 等），在此填地址即可。
    # 与 embedding 同属「本地推理微服务」——用户/admin 不可配，连接信息从 env 读。
    # 与 embedding 的唯一不对称：rerank 是 fail-open 设计（挂了降级原序），
    # 故保留 enabled 开关供运维降级（embedding 无开关因其挂了 RAG 直接崩）。
    rerank_enabled: bool = True
    rerank_base_url: str = "http://localhost:7998"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_key: str = ""  # 本地服务通常不校验 key，留空

    # 【v1.1】记忆热度/淘汰配置
    # 注意端口规划：7997 embedding / 7998 rerank / 7999 NLI（避免与 rerank 冲突）。
    memory_limit: int = 200                       # 单用户记忆上限
    memory_half_life_days: int = 30               # 热度衰减半衰期（天）
    memory_grace_days: int = 7                    # 新记忆豁免期（天）
    nli_base_url: str = "http://localhost:7999"   # NLI 矛盾判断服务地址

    # drawio 渲染微服务（apps/drawio-render/，端口 8001）。
    # 跑 draw.io desktop headless CLI 把 XML 渲染成 PNG。软依赖（fail-closed）：
    # 服务不可用时 figure 生成整体报错，不降级、不留半成品。api 启动不 depends_on 它。
    # 端口规划：7997 embedding / 7998 rerank / 7999 NLI / 8000 api / 8001 drawio。
    drawio_base_url: str = "http://localhost:8001"

    # Firecrawl（网页摄入,本地自部署微服务,与 embedding/rerank 同范式）。
    # 由 docker-compose.yml 的 firecrawl 服务提供(api+worker + playwright + redis)。
    # 纯 env 配置（无 admin 配置页）：base_url 指本地服务,api_key 需与 firecrawl 容器一致。
    # 可用性 = 服务连通性,启动时由 main.py 探活告警,无 enabled 开关。
    firecrawl_api_key: str = "fc-local-default-key"
    firecrawl_base_url: str = "http://localhost:3002"

    # MinerU（PDF→Markdown 云端解析;全局 token 存 SystemSetting,env 仅兜底）
    # 未配置时 PDF 解析降级到 pypdf 纯文本提取。
    mineru_api_token: str = ""
    mineru_base_url: str = "https://mineru.net"
    mineru_model_version: str = "vlm"  # vlm（高精度）/ pipeline（快）

    # 腾讯 ima 实时检索源（admin 全局配置，所有用户共享单源）
    # 两步检索：① search_knowledge_base 发现相关知识库（含订阅库，返回 kb_id）
    #           ② search_knowledge 按 kb_id 检索文档片段（title/highlight_content）
    # 凭据加密存 SystemSetting（ima_config）；鉴权用 ima 官方自定义 header。
    # env 仅兜底：admin 未在控制台配置时，可经这两个环境变量提供。
    ima_client_id: str = ""
    ima_api_key: str = ""
    ima_search_kb_url: str = "https://ima.qq.com/openapi/wiki/v1/search_knowledge_base"
    ima_search_doc_url: str = "https://ima.qq.com/openapi/wiki/v1/search_knowledge"
    ima_search_timeout: float = 8.0  # 外网 + 两步检索，给足时间；超时即降级

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

    # 日志（见 app/core/logging.py）。env 可控。
    log_level: str = "INFO"            # DEBUG/INFO/WARNING/ERROR
    log_dir: str = "logs"              # 文件 sink 目录（容器挂 volume）
    log_file_enabled: bool = True      # 是否落盘；测试可设 False 关掉

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
