"""全篇质量报告测试：跨章节一致性检查、章节定位、趋势端点。"""
import uuid


def _login(client, registered_user):
    r = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


def _create_project_with_sections(db_session, registered_user):
    from app.models import Project, Section
    uid = uuid.UUID(registered_user["id"])
    p = Project(user_id=uid, title="质量报告测试项目")
    db_session.add(p)
    db_session.commit()
    for i, (key, title) in enumerate([
        ("problem", "技术问题"),
        ("solution", "技术方案"),
        ("effect", "技术效果"),
    ], 1):
        s = Section(
            project_id=p.id, template_section_id=key, key=key,
            title=title, order=i, status="drafting",
            content={"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": f"{title}内容"}]}
            ]},
        )
        db_session.add(s)
    db_session.commit()
    return str(p.id)


def test_aggregate_section_issues(db_session, registered_user):
    """章节定位聚合：evidence/suggestion 含章节标题的归到对应章节。"""
    from app.services.review_service import _aggregate_section_issues
    from app.models import Project
    uid = uuid.UUID(registered_user["id"])
    pid = _create_project_with_sections(db_session, registered_user)

    dimension_scores = [
        {"key": "clarity", "name": "清晰度", "weight": 0.3, "score": 70,
         "evidence": "技术问题章节描述不够清楚", "suggestion": "补充技术问题细节"},
        {"key": "completeness", "name": "完整度", "weight": 0.3, "score": 80,
         "evidence": "技术方案章节较完整", "suggestion": "已达标"},
    ]
    result = _aggregate_section_issues(db_session, uuid.UUID(pid), dimension_scores)

    # 「技术问题」标题命中 clarity 的 evidence/suggestion
    titles = [r["section_title"] for r in result]
    assert "技术问题" in titles
    # 验证结构
    problem_sec = next(r for r in result if r["section_title"] == "技术问题")
    assert len(problem_sec["issues"]) > 0
    assert "section_key" in problem_sec


def test_check_cross_section_consistency_mocked(db_session, registered_user, monkeypatch):
    """跨章节一致性检查（mock LLM 返回空 issues）。"""
    from app.services import review_service
    from unittest.mock import MagicMock

    def mock_get_llm(llm_config):
        mock_llm = MagicMock()
        # 让 with_structured_output 抛 AttributeError，走 fallback 文本解析路径
        mock_llm.with_structured_output.side_effect = AttributeError("not supported")
        mock_resp = MagicMock()
        mock_resp.content = '{"issues": []}'
        mock_llm.invoke.return_value = mock_resp
        return mock_llm

    monkeypatch.setattr(review_service, "get_llm", mock_get_llm)

    sections = {"技术问题": "内容A", "技术方案": "内容B"}
    from app.services.llm_config_service import ResolvedChatConfig
    config = ResolvedChatConfig(
        base_url="http://test", api_key="k", model="m", source="global"
    )
    result = review_service._check_cross_section_consistency(sections, config)
    assert result == []


def test_review_record_has_new_fields(db_session, registered_user):
    """新建 ReviewRecord 默认 cross_section_issues/section_issues 为空列表。"""
    from app.models import ReviewRecord, Project
    uid = uuid.UUID(registered_user["id"])
    p = Project(user_id=uid, title="字段测试")
    db_session.add(p)
    db_session.commit()

    r = ReviewRecord(
        project_id=p.id, user_id=uid, rubric_snapshot=[], round=1,
        total_score=80, dimension_scores=[],
    )
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    assert r.cross_section_issues == []
    assert r.section_issues == []


def test_trend_endpoint(client, registered_user, db_session):
    """趋势端点返回多轮审查数据（升序）。"""
    from app.models import ReviewRecord, Project
    _login(client, registered_user)
    pid = _create_project_with_sections(db_session, registered_user)
    uid = uuid.UUID(registered_user["id"])
    proj = db_session.get(Project, uuid.UUID(pid))

    # 造 2 轮审查记录
    for i, score in enumerate([60, 75], 1):
        r = ReviewRecord(
            project_id=proj.id, user_id=uid, rubric_snapshot=[], round=i,
            total_score=score, dimension_scores=[
                {"key": "clarity", "name": "清晰度", "weight": 1.0, "score": score}
            ],
        )
        db_session.add(r)
    db_session.commit()

    resp = client.get(f"/api/v1/projects/{pid}/reviews/trend")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["total_score"] == 60
    assert data[1]["total_score"] == 75
    assert "clarity" in data[0]["dimension_scores"]


# ── T2 批 2：跨章节 issue 结构化定位（location_section_keys）──────────────────


class TestLocationSectionKeys:
    """spec §3.2.1：keys 从 prompt 清单取值；LLM 未给时按标题回填；幻觉 key 过滤。"""

    def test_schema_field_default_empty(self):
        """新字段默认空列表——旧 ReviewRecord JSON（无此字段）可解析（向后兼容）。"""
        from app.ai.schemas.review_schema import CrossSectionIssue
        issue = CrossSectionIssue(
            type="terminology", description="d",
            location_sections=["技术问题"], suggestion="s",
        )
        assert issue.location_section_keys == []

    def test_schema_accepts_keys(self):
        from app.ai.schemas.review_schema import CrossSectionIssue
        issue = CrossSectionIssue(
            type="terminology", description="d",
            location_sections=["技术问题"], suggestion="s",
            location_section_keys=["problem", "solution"],
        )
        assert issue.location_section_keys == ["problem", "solution"]

    def test_prompt_lists_key_manifest(self):
        """build_consistency_prompt 传 title_key_map 时附「key: 标题」清单，
        并要求 location_section_keys 从清单取值（spec §3.2.1-2）。"""
        from app.ai.review_prompts import build_consistency_prompt
        prompt = build_consistency_prompt(
            {"技术问题": "内容A", "技术方案": "内容B"},
            title_key_map={"技术问题": "problem", "技术方案": "solution"},
        )
        assert "problem: 技术问题" in prompt
        assert "solution: 技术方案" in prompt
        assert "location_section_keys" in prompt

    def test_prompt_without_map_unchanged_shape(self):
        """不传 title_key_map（旧调用方）：prompt 无 key 清单，正常构造。"""
        from app.ai.review_prompts import build_consistency_prompt
        prompt = build_consistency_prompt({"技术问题": "内容A"})
        assert "技术问题" in prompt
        assert "location_section_keys" not in prompt

    def _mock_structured_llm(self, monkeypatch, report):
        """mock get_llm：with_structured_output 正常工作，invoke 返回预置 ConsistencyReport。"""
        from unittest.mock import MagicMock
        from app.services import review_service

        mock_llm = MagicMock()
        structured = MagicMock()
        structured.invoke.return_value = report
        mock_llm.with_structured_output.return_value = structured
        monkeypatch.setattr(review_service, "get_llm", lambda cfg: mock_llm)

    def test_structured_output_keeps_keys(self, db_session, registered_user, monkeypatch):
        """LLM 正常返回 keys → 保留（roundtrip）。"""
        from app.ai.schemas.review_schema import ConsistencyReport, CrossSectionIssue
        from app.services import review_service
        from app.services.llm_config_service import ResolvedChatConfig

        report = ConsistencyReport(issues=[
            CrossSectionIssue(
                type="terminology", description="术语不一致",
                location_sections=["技术问题", "技术方案"], suggestion="统一为「控制器」",
                location_section_keys=["problem", "solution"],
            ),
        ])
        self._mock_structured_llm(monkeypatch, report)
        config = ResolvedChatConfig(base_url="http://t", api_key="k", model="m", source="global")
        result = review_service._check_cross_section_consistency(
            {"技术问题": "A", "技术方案": "B"}, config,
            title_key_map={"技术问题": "problem", "技术方案": "solution"},
        )
        assert result[0]["location_section_keys"] == ["problem", "solution"]

    def test_backfill_keys_from_titles(self, db_session, registered_user, monkeypatch):
        """LLM 只给标题（未给 keys）→ 按 title_key_map 回填（spec §3.2.1-3）。"""
        from app.ai.schemas.review_schema import ConsistencyReport, CrossSectionIssue
        from app.services import review_service
        from app.services.llm_config_service import ResolvedChatConfig

        report = ConsistencyReport(issues=[
            CrossSectionIssue(
                type="terminology", description="术语不一致",
                location_sections=["技术方案"], suggestion="统一",
            ),
        ])
        self._mock_structured_llm(monkeypatch, report)
        config = ResolvedChatConfig(base_url="http://t", api_key="k", model="m", source="global")
        result = review_service._check_cross_section_consistency(
            {"技术方案": "B"}, config,
            title_key_map={"技术方案": "solution"},
        )
        assert result[0]["location_section_keys"] == ["solution"]

    def test_backfill_no_match_leaves_empty(self, db_session, registered_user, monkeypatch):
        """标题在 map 中无匹配 → keys 留空（前端仅展示不提供 chip 入口，spec 边界 #11）。"""
        from app.ai.schemas.review_schema import ConsistencyReport, CrossSectionIssue
        from app.services import review_service
        from app.services.llm_config_service import ResolvedChatConfig

        report = ConsistencyReport(issues=[
            CrossSectionIssue(
                type="other", description="d",
                location_sections=["不存在的标题"], suggestion="s",
            ),
        ])
        self._mock_structured_llm(monkeypatch, report)
        config = ResolvedChatConfig(base_url="http://t", api_key="k", model="m", source="global")
        result = review_service._check_cross_section_consistency(
            {"A": "B"}, config, title_key_map={"A": "a"},
        )
        assert result[0]["location_section_keys"] == []

    def test_hallucinated_key_filtered(self, db_session, registered_user, monkeypatch):
        """LLM 给了不在 map 值集合的 key（幻觉）→ 过滤掉（spec §3.2.1-3 后处理）。"""
        from app.ai.schemas.review_schema import ConsistencyReport, CrossSectionIssue
        from app.services import review_service
        from app.services.llm_config_service import ResolvedChatConfig

        report = ConsistencyReport(issues=[
            CrossSectionIssue(
                type="terminology", description="d",
                location_sections=["技术方案"], suggestion="s",
                location_section_keys=["claims", "solution"],  # claims 不存在
            ),
        ])
        self._mock_structured_llm(monkeypatch, report)
        config = ResolvedChatConfig(base_url="http://t", api_key="k", model="m", source="global")
        result = review_service._check_cross_section_consistency(
            {"技术方案": "B"}, config,
            title_key_map={"技术方案": "solution"},
        )
        assert result[0]["location_section_keys"] == ["solution"]
