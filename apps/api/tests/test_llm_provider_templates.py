"""provider 模板静态数据测试。"""

from app.services.llm_provider_templates import PROVIDER_TEMPLATES, get_provider_template, ProviderTemplate


def test_templates_non_empty():
    assert len(PROVIDER_TEMPLATES) == 7


def test_each_template_has_required_fields():
    for t in PROVIDER_TEMPLATES:
        assert t.id, f"{t} 缺 id"
        assert t.name, f"{t.id} 缺 name"
        assert t.models_endpoint, f"{t.id} 缺 models_endpoint"
        # base_url / default_model 对 custom 模板可为空，其余必填
        if t.id != "custom":
            assert t.base_url, f"{t.id} 缺 base_url"
            assert t.default_model, f"{t.id} 缺 default_model"


def test_ids_unique():
    ids = [t.id for t in PROVIDER_TEMPLATES]
    assert len(ids) == len(set(ids))


def test_custom_template_present():
    """custom 模板必须存在（前端「自定义」入口）。"""
    assert get_provider_template("custom") is not None


def test_zhipu_template_fields():
    t = get_provider_template("zhipu")
    assert t is not None
    assert "bigmodel" in t.base_url
    assert t.default_embedding_model == "embedding-3"
    assert t.models_endpoint == "/models"


def test_ollama_uses_tags_endpoint():
    t = get_provider_template("ollama")
    assert t is not None
    assert t.models_endpoint == "/api/tags"


def test_get_template_unknown_returns_none():
    assert get_provider_template("nonexistent") is None


def test_no_embedding_model_providers():
    """deepseek / openrouter 无 embedding 模型（embedding 测试逻辑依赖此契约）。"""
    assert get_provider_template("deepseek").default_embedding_model is None
    assert get_provider_template("openrouter").default_embedding_model is None


def test_models_endpoint_values():
    """models_endpoint 必为 /models（OpenAI 兼容）或 /api/tags（Ollama），防拼写错误。"""
    allowed = {"/models", "/api/tags"}
    for t in PROVIDER_TEMPLATES:
        assert t.models_endpoint in allowed, f"{t.id} 的 models_endpoint={t.models_endpoint!r} 非法"
