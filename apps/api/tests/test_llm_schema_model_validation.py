"""1214 修复闸 3：schema 源头拒存空 model。

根因：admin/用户保存配置时漏填 model，schema 无 min_length 校验，
空串一路存进库 → 解析时（闸 2 之前）透传给 ChatOpenAI → 智谱 1214。
这里在 API 入口 schema 拦住，让空 model 在落库前就被 422 拒绝。

注：UserLLMUpdateRequest.model 保持可选（None=不改），不在此约束，
靠闸 1/2 兜底。
"""

import pytest
from pydantic import ValidationError


def test_global_llm_settings_rejects_empty_model():
    """GlobalLLMSettings 的 model 给了空串 → ValidationError。"""
    from app.api.admin.console import GlobalLLMSettings
    with pytest.raises(ValidationError):
        GlobalLLMSettings(enabled=True, model="")


def test_global_llm_settings_allows_none_model():
    """GlobalLLMSettings 的 model 不传 → None（保留可选语义，不更新时用）。"""
    from app.api.admin.console import GlobalLLMSettings
    s = GlobalLLMSettings(enabled=True)
    assert s.model is None


def test_custom_create_rejects_empty_model():
    """UserLLMCreateRequest 的 model 空串 → ValidationError。"""
    from app.api.settings import UserLLMCreateRequest
    with pytest.raises(ValidationError):
        UserLLMCreateRequest(
            name="公司Key", base_url="https://api.example.com",
            api_key="sk-test", model="",
        )


def test_custom_test_rejects_empty_model():
    """UserLLMTestRequest 的 model 空串 → ValidationError（测试连通性也必须有 model）。"""
    from app.api.settings import UserLLMTestRequest
    with pytest.raises(ValidationError):
        UserLLMTestRequest(
            base_url="https://api.example.com", api_key="sk-test", model="",
        )


def test_custom_update_model_allows_none():
    """UserLLMUpdateRequest.model=None → 合法（表示不更新 model，可选更新语义）。"""
    from app.api.settings import UserLLMUpdateRequest
    req = UserLLMUpdateRequest()
    assert req.model is None  # None=不改，不应被拒
