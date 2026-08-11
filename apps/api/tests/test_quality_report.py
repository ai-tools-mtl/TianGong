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
