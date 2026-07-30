"""[S5] 审查评分结构化输出测试（spec 2026-07-29-prompt-content-design §4 S5 / 支撑层 P0）。

此前 _score_dimension 用 _parse_json_response 的脆弱正则解析 JSON，
该正则排除花括号，【连嵌套 JSON 都解析不了】，且失败时静默退化为 (50, ...)。

S5 改用 with_structured_output(DimensionScore) 强约束输出，并对不支持原生
structured output 的 provider（D1 决策）保留正则解析作 fallback。

注：test_review_service.py 测的是知识库审核（KnowledgeReview），本文件专测评分解析。
"""
import json


def _criterion():
    """构造一个测试用评分维度。"""
    return {
        "key": "completeness",
        "name": "完整性",
        "weight": 1,
        "scoring_guide": {"80-100": "完整", "0-79": "不完整"},
    }


def test_dimension_score_schema_fields():
    """[S5] DimensionScore schema 有 score/evidence/suggestion 三个字段。"""
    from app.ai.schemas.review_schema import DimensionScore

    ds = DimensionScore(score=85, evidence="方案完整", suggestion="可补充实施例")
    assert ds.score == 85
    assert ds.evidence == "方案完整"
    assert ds.suggestion == "可补充实施例"


def test_dimension_score_score_range_clamped():
    """[S5] score 超范围时 schema 层校验（Pydantic ge/le 约束）。"""
    import pytest
    from pydantic import ValidationError

    from app.ai.schemas.review_schema import DimensionScore

    with pytest.raises(ValidationError):
        DimensionScore(score=150, evidence="x", suggestion="y")  # >100
    with pytest.raises(ValidationError):
        DimensionScore(score=-1, evidence="x", suggestion="y")   # <0


def test_score_dimension_uses_structured_output(db_session, monkeypatch):
    """[S5] _score_dimension 用 with_structured_output，返回结构化结果。"""
    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    class _FakeStructuredLLM:
        """模拟 with_structured_output 链：invoke 返回 DimensionScore 对象。"""
        def with_structured_output(self, schema):
            self._schema = schema
            return self

        def invoke(self, messages):
            return self._schema(score=82, evidence="引用了交底书内容", suggestion="建议补充")

    # mock get_llm 返回的实例支持 with_structured_output
    monkeypatch.setattr(review_service, "get_llm",
                        lambda config, **kw: _FakeStructuredLLM())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    score, evidence, suggestion = review_service._score_dimension(_criterion(), {}, config)

    assert score == 82
    assert evidence == "引用了交底书内容"
    assert suggestion == "建议补充"


def test_score_dimension_fallback_when_structured_output_unsupported(db_session, monkeypatch):
    """[S5] provider 不支持 structured output 时，fallback 到正则解析（D1 兼容）。

    模拟 with_structured_output 抛异常（如某些 provider 不支持），
    验证退回 _parse_json_response 路径仍能解析合法 JSON 文本。
    """
    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    class _FakePlainLLM:
        """不支持 structured output：with_structured_output 抛异常，invoke 返回文本。"""
        def with_structured_output(self, schema):
            raise NotImplementedError("provider 不支持 structured output")

        def invoke(self, messages):
            # 返回合法 JSON 文本（fallback 正则解析路径）
            return type("_Resp", (), {
                "content": '{"score": 78, "evidence": "证据", "suggestion": "建议"}'
            })()

    monkeypatch.setattr(review_service, "get_llm",
                        lambda config, **kw: _FakePlainLLM())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    score, evidence, suggestion = review_service._score_dimension(_criterion(), {}, config)

    assert score == 78
    assert evidence == "证据"
    assert suggestion == "建议"


def test_parse_json_response_handles_nested_json():
    """[S5 回归 G1] 正则 fallback 路径必须能解析花括号嵌套 JSON。

    旧正则 r"\\{[^{}]*\\}" 的 [^{}]* 排除花括号，遇到 dict 嵌 dict 直接匹配失败。
    （注意：嵌 list 用方括号不触发此 bug，必须嵌花括号 dict 才能复现。）
    S5 的 fallback 应能处理嵌套（用更健壮的提取）。
    """
    from app.services.review_service import _parse_json_response

    # 花括号嵌套（evidence 里嵌了 dict）——旧正则必挂在内层 }
    nested = '前缀 {"score": 90, "evidence": {"quote": "原文", "loc": "第2段"}, "suggestion": "建议"} 后缀'
    data = _parse_json_response(nested)
    assert data["score"] == 90
    assert data["evidence"]["quote"] == "原文"


def test_score_dimension_fallback_on_total_failure(db_session, monkeypatch):
    """[S5] structured output 和正则都失败时，退回 (50, 评分失败, 请重试) 兜底。"""
    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    class _FakeBrokenLLM:
        def with_structured_output(self, schema):
            raise NotImplementedError()

        def invoke(self, messages):
            raise RuntimeError("provider 完全不可用")

    monkeypatch.setattr(review_service, "get_llm",
                        lambda config, **kw: _FakeBrokenLLM())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    score, evidence, suggestion = review_service._score_dimension(_criterion(), {}, config)

    assert score == 50
    assert "失败" in evidence
