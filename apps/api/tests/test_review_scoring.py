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


def test_score_dimension_fallback_on_server_side_reject(db_session, monkeypatch):
    """[dogfood 2026-08-19] 服务端 400 拒绝 response_format（DeepSeek 实测
    「This response_format type is unavailable now」）也必须走文本 fallback。

    旧版只捕获本地 NotImplementedError/AttributeError，服务端 BadRequestError
    穿透后被外层 except Exception 吞成 50 分兜底——这是审查页「全 50 分评分失败」
    事故的第二层根因（第一层：静默吞异常）。普通 invoke 是通的，fallback 后即可用。
    """
    import httpx
    from openai import BadRequestError

    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    def _deepseek_400() -> BadRequestError:
        resp = httpx.Response(
            400, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        )
        return BadRequestError(
            "Error code: 400 - {'error': {'message': 'This response_format "
            "type is unavailable now', 'type': 'invalid_request_error'}}",
            response=resp, body=None,
        )

    # langchain 结构化链与普通调用共用 invoke——用调用次数区分两阶段：
    # 第 1 次（结构化链内）抛 400，第 2 次（文本 fallback）返回合法 JSON。
    class _TwoPhaseLLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == 1:
                raise _deepseek_400()
            return type("_Resp", (), {
                "content": '{"score": 88, "evidence": "证据B", "suggestion": "建议B"}'
            })()

    monkeypatch.setattr(review_service, "get_llm",
                        lambda config, **kw: _TwoPhaseLLM())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="deepseek-v4-pro", source="global")
    score, evidence, suggestion = review_service._score_dimension(_criterion(), {}, config)

    assert score == 88
    assert evidence == "证据B"
    assert suggestion == "建议B"


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


def test_score_dimension_raises_on_total_failure(db_session, monkeypatch):
    """[失败治理 2026-08-19] structured output 和正则都失败时抛原始异常，
    不再静默退回 (50, 评分失败)——那是审查页「全 50 分废报告」事故的根因
    （LLM 余额不足被吞，用户只看到 toast「审查完成」）。降级/报错由 run_review 统一决定。
    """
    import pytest
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
    with pytest.raises(RuntimeError, match="provider 完全不可用"):
        review_service._score_dimension(_criterion(), {}, config)


# ── run_review 失败治理（dogfood 2026-08-19：LLM 全挂必须报错，不许落废报告）──


def _make_review_project(db_session):
    """建 用户 + 项目 + 章节 + 系统默认 rubric，返回 (user, project)。"""
    import uuid as _uuid

    from app.core.security import hash_password
    from app.models import Section, User
    from app.services import project_service as ps
    from app.services.seed_service import ensure_default_rubric, ensure_default_template

    ensure_default_template(db_session)
    ensure_default_rubric(db_session)
    u = User(
        username=f"rvw_{_uuid.uuid4().hex[:8]}",
        email=f"rvw_{_uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="审查测试用户",
    )
    db_session.add(u)
    db_session.commit()
    project = ps.create_project(db_session, user=u, title="失败治理测试项目")
    sec = Section(
        project_id=project.id, template_section_id="solution",
        key="solution", title="技术方案",
        order=1, content={"type": "doc", "content": []},
    )
    db_session.add(sec)
    db_session.commit()
    return u, project


def _patch_llm_all_fail(monkeypatch):
    """mock get_llm 全抛 429 余额不足（智谱 1113 真实报文）。"""
    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    class _InsufficientBalanceLLM:
        def with_structured_output(self, schema):
            raise RuntimeError(
                "Error code: 429 - {'error': {'code': '1113', 'message': '余额不足或无可用资源包,请充值。'}}"
            )

    config = ResolvedChatConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4", api_key="k", model="glm-4.7", source="env"
    )
    monkeypatch.setattr(review_service, "resolve_chat_config", lambda db, user_id: config)
    monkeypatch.setattr(review_service, "get_llm", lambda cfg, **kw: _InsufficientBalanceLLM())


def test_run_review_all_llm_failed_raises_and_no_record(db_session, monkeypatch):
    """全部评分调用失败 → 抛 ValidationError（余额友好文案）且不落库。"""
    import pytest
    from sqlalchemy import select

    from app.core.exceptions import ValidationError
    from app.models import ReviewRecord
    from app.services import review_service

    u, project = _make_review_project(db_session)
    _patch_llm_all_fail(monkeypatch)

    with pytest.raises(ValidationError, match="余额不足"):
        review_service.run_review(db_session, user_id=u.id, project_id=str(project.id))

    assert db_session.scalar(
        select(ReviewRecord).where(ReviewRecord.project_id == project.id)
    ) is None, "LLM 全挂时不允许落全 50 分废报告"


def test_run_review_partial_failure_still_records(db_session, monkeypatch):
    """部分 run 失败 → 照常落库，失败 run 兜底 50（可用性优先，报告里可见「评分失败」）。"""
    from sqlalchemy import select

    from app.models import ReviewRecord
    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    u, project = _make_review_project(db_session)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="m", source="env")
    monkeypatch.setattr(review_service, "resolve_chat_config", lambda db, user_id: config)

    calls = {"n": 0}

    class _FlakyLLM:
        """首次调用成功、之后全失败（structured 链只构造一次——同一实例）。"""
        def __init__(self):
            self.ok = True

        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            calls["n"] += 1
            if self.ok:
                self.ok = False
                from app.ai.schemas.review_schema import DimensionScore
                return DimensionScore(score=90, evidence="证据", suggestion="建议")
            raise RuntimeError("Error code: 429 - 余额不足")

    monkeypatch.setattr(review_service, "get_llm", lambda cfg, **kw: _FlakyLLM())

    record = review_service.run_review(db_session, user_id=u.id, project_id=str(project.id))

    assert record.total_score >= 0  # 正常落库（部分失败兜底 50 拉低总分）
    assert db_session.scalar(
        select(ReviewRecord).where(ReviewRecord.project_id == project.id)
    ) is not None
    assert calls["n"] >= 1


def test_cross_section_issues_normalized_on_text_fallback(monkeypatch):
    """[dogfood 2026-08-19 回归] 文本 fallback 产出缺字段 → 规范化补齐契约字段。

    实测 DeepSeek 文本路径 LLM 只给 location_section_keys 不给
    location_sections，落库后前端 issue.location_sections.length 直接崩溃。
    后端 _postprocess 单点规范化（D14），保证五字段恒齐。
    """
    import httpx
    from openai import BadRequestError

    from app.services import review_service
    from app.services.llm_config_service import ResolvedChatConfig

    class _TextFallbackLLM:
        """结构化 400 → 文本路径返回缺字段的 JSON。"""

        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == 1:
                resp = httpx.Response(
                    400, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
                )
                raise BadRequestError("400 response_format unavailable", response=resp, body=None)
            return type("_Resp", (), {
                "content": (
                    '{"issues": [{"type": "terminology", "description": "术语不一致", '
                    '"suggestion": "统一术语", "location_section_keys": ["problem"]}]}'
                )
            })()

    monkeypatch.setattr(review_service, "get_llm", lambda cfg, **kw: _TextFallbackLLM())
    cfg = ResolvedChatConfig(base_url="http://x", api_key="k", model="deepseek-v4-pro", source="global")

    issues = review_service._check_cross_section_consistency(
        {"技术领域": "内容", "发明目的与技术问题": "内容"}, cfg,
        title_key_map={"发明目的与技术问题": "problem"},
    )

    assert len(issues) == 1
    issue = issues[0]
    # 契约五字段恒齐（缺的补空，不缺的保留）
    assert issue["location_sections"] == []
    assert issue["location_section_keys"] == ["problem"]  # 有效 key 保留，不清空
    assert issue["type"] == "terminology"
    assert issue["description"] == "术语不一致"
    assert issue["suggestion"] == "统一术语"


# ── 审查进行中互斥（dogfood 2026-08-19：离开页面重进看不到后台任务、可重复触发）──


def test_run_review_conflict_when_already_running(db_session):
    """同项目审查进行中 → 再次触发 409；status 端点语义（is_review_running）正确。"""
    import pytest

    from app.core.exceptions import ConflictError
    from app.services import review_service as rs

    u, project = _make_review_project(db_session)

    assert rs._try_acquire_review_lock(project.id) is None  # 占坑成功
    try:
        with pytest.raises(ConflictError, match="正在进行中"):
            rs.run_review(db_session, user_id=u.id, project_id=str(project.id))
        assert rs.is_review_running(project.id) is not None  # 仍报进行中
    finally:
        rs._release_review_lock(project.id)
    assert rs.is_review_running(project.id) is None


def test_running_stale_marker_expires(db_session):
    """残留标记（超过 _RUNNING_STALE_SECONDS）自动视为失效，可重新占坑。"""
    import time as _time
    import uuid as _uuid

    from app.services import review_service as rs

    pid = _uuid.uuid4()
    stale = _time.time() - rs._RUNNING_STALE_SECONDS - 1
    rs._running_reviews[pid] = {"started_at": stale, "last_touch": stale}
    assert rs.is_review_running(pid) is None
    assert rs._try_acquire_review_lock(pid) is None
    rs._release_review_lock(pid)


def test_run_review_lock_released_on_llm_failure(db_session, monkeypatch):
    """LLM 全挂抛 ValidationError 后锁必须释放（finally），不能卡死后续重试。"""
    import uuid as _uuid

    import pytest

    from app.core.exceptions import ValidationError
    from app.services import review_service as rs

    u, project = _make_review_project(db_session)
    _patch_llm_all_fail(monkeypatch)

    with pytest.raises(ValidationError):
        rs.run_review(db_session, user_id=u.id, project_id=str(project.id))

    assert rs.is_review_running(project.id) is None


def test_review_status_and_conflict_api(client, db_session):
    """API 层：status 端点反映进行中；进行中 POST review → 409（不碰 LLM）。"""
    from app.core.security import hash_password
    from app.models import User
    from app.services import project_service as ps
    from app.services import review_service as rs
    from app.services.seed_service import ensure_default_template

    ensure_default_template(db_session)
    a = User(
        username="mutex_user", email="mutex_user@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="互斥测试",
    )
    db_session.add(a)
    db_session.commit()
    project = ps.create_project(db_session, user=a, title="互斥测试项目")

    res = client.post("/api/v1/auth/login", json={"username": "mutex_user", "password": "Pass1234!"})
    assert res.status_code == 200, res.text

    rs._try_acquire_review_lock(project.id)
    try:
        resp = client.get(f"/api/v1/projects/{project.id}/review/status")
        assert resp.status_code == 200
        assert resp.json()["running"] is True
        assert resp.json()["started_at"] is not None

        resp = client.post(f"/api/v1/projects/{project.id}/review")
        assert resp.status_code == 409, (resp.status_code, resp.text)
        assert "正在进行中" in resp.json()["message"]
    finally:
        rs._release_review_lock(project.id)

    resp = client.get(f"/api/v1/projects/{project.id}/review/status")
    assert resp.json()["running"] is False


def test_touch_review_lock_refreshes_stale_window():
    """心跳续期：stale 窗口从「上次进度」起算而非「占坑」起算，且不动 started_at。

    推进中的审查（单次超 _RUNNING_STALE_SECONDS 的慢 LLM 链）不因总时长
    超阈值被误判失效——否则第二个触发可并发进入，重复落库（锁要防的场景）。
    started_at 保持真实起点：/review/status 与 409「已进行 X 分钟」据此展示。
    """
    import time as _time
    import uuid as _uuid

    from app.services import review_service as rs

    pid = _uuid.uuid4()
    stale = _time.time() - rs._RUNNING_STALE_SECONDS - 10  # 原占坑早已超阈值
    rs._running_reviews[pid] = {"started_at": stale, "last_touch": stale}
    assert rs.is_review_running(pid) is None  # 未续期 → 已 stale

    rs._touch_review_lock(pid)  # 评分循环完成一次调用，续期
    assert rs.is_review_running(pid) is not None  # 从最后进度起算，仍在窗口内
    assert rs._try_acquire_review_lock(pid) is not None  # 不能被重新占坑
    assert rs.is_review_running(pid) == stale  # 对外仍报真实起点，不被心跳改写

    rs._release_review_lock(pid)
    assert rs.is_review_running(pid) is None
