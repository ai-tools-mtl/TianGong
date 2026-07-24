"""LLM provider 模板预设（静态数据）。

供前端「添加配置」时选择模板自动填 base_url + 默认模型。决策 D2：放后端而非前端硬编码，
便于按部署环境注入不同模板集（内网常需自定义中转网关），且 base_url/默认模型可随供应商调整统一改一处。

每条模板的 models_endpoint 是**追加在 base_url 末尾的尾段**，消费方统一做字符串拼接：
`base_url.rstrip("/") + models_endpoint`。
- OpenAI 兼容供应商（base_url 已含版本段如 /v1、/v4）→ models_endpoint="/models"
  （例：zhipu .../v4 + /models = .../v4/models；openai .../v1 + /models = .../v1/models）
- Ollama（base_url 无版本段）→ models_endpoint="/api/tags"
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderTemplate:
    id: str                                  # "zhipu" / "openai" / "deepseek" / "openrouter" / "moonshot" / "ollama" / "custom"
    name: str                                # 展示名
    base_url: str                            # 默认 base_url（custom 为空）
    default_model: str                       # 默认 chat 模型名（custom 为空）
    default_embedding_model: str | None      # 默认 embedding 模型名（无则 None）
    models_endpoint: str                     # 追加在 base_url 末尾的尾段；消费方用 base_url.rstrip("/") + models_endpoint 拼接。OpenAI 兼容="/models"，Ollama="/api/tags"
    docs_url: str | None                     # 文档/官网链接（卡片「如何获取 Key」）
    note: str | None                         # 提示文案


PROVIDER_TEMPLATES: tuple[ProviderTemplate, ...] = (
    ProviderTemplate(
        id="zhipu", name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        default_embedding_model="embedding-3",
        models_endpoint="/models",
        docs_url="https://open.bigmodel.cn",
        note="智谱开放平台，需在控制台开通对应模型",
    ),
    ProviderTemplate(
        id="deepseek", name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        default_embedding_model=None,
        models_endpoint="/models",
        docs_url="https://platform.deepseek.com",
        note=None,
    ),
    ProviderTemplate(
        id="openai", name="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        default_embedding_model="text-embedding-3-small",
        models_endpoint="/models",
        docs_url="https://platform.openai.com/api-keys",
        note=None,
    ),
    ProviderTemplate(
        id="openrouter", name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        default_embedding_model=None,
        models_endpoint="/models",
        docs_url="https://openrouter.ai/keys",
        note=None,
    ),
    ProviderTemplate(
        id="moonshot", name="Moonshot Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        default_embedding_model=None,
        models_endpoint="/models",
        docs_url="https://platform.moonshot.cn",
        note=None,
    ),
    ProviderTemplate(
        id="ollama", name="Ollama（本地）",
        base_url="http://localhost:11434",
        default_model="qwen2.5:7b",
        default_embedding_model="nomic-embed-text",
        models_endpoint="/api/tags",
        docs_url="https://ollama.com",
        note="本地部署，无需 API Key（Key 字段任意填）",
    ),
    ProviderTemplate(
        id="custom", name="自定义（OpenAI 兼容）",
        base_url="",
        default_model="",
        default_embedding_model=None,
        models_endpoint="/models",
        docs_url=None,
        note="填写你的 OpenAI 兼容端点",
    ),
)

_BY_ID: dict[str, ProviderTemplate] = {t.id: t for t in PROVIDER_TEMPLATES}


def get_provider_template(template_id: str) -> ProviderTemplate | None:
    """按 id 取模板，未知返回 None。"""
    return _BY_ID.get(template_id)
