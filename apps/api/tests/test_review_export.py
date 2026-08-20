"""审查报告 PDF 导出测试。

核心回归（dogfood 2026-08-19）：weasyprint 的 GTK/Pango 系统库缺失时
（Windows 裸机实测 cannot load library 'libgobject-2.0-0'），
导出必须 fail-closed 抛 ServiceUnavailableError（503 + 中文指引），
不能裸 500——生产 Docker 已装 libpango，此错只在无 GTK 环境出现。
"""
import sys
import types

import pytest

from app.core.exceptions import ServiceUnavailableError
from app.core.security import hash_password
from app.models import Project, ReviewRecord, User


@pytest.fixture
def project_with_review(db_session):
    u = User(
        username="export_test", email="export_test@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="导出测试",
    )
    db_session.add(u)
    db_session.commit()
    p = Project(user_id=u.id, title="导出测试项目")
    db_session.add(p)
    db_session.commit()
    rec = ReviewRecord(
        project_id=p.id, user_id=u.id,
        rubric_snapshot=[], round=1, total_score=75, previous_score=None,
        dimension_scores=[
            {"key": "novelty", "name": "新颖性", "weight": 0.25,
             "score": 95, "run_scores": [95], "evidence": "证据", "suggestion": "已达标"},
        ],
        resolved_issues=[], remaining_issues=["建议补充实施例"],
        cross_section_issues=[], section_issues=[],
    )
    db_session.add(rec)
    db_session.commit()
    return p, rec


def test_export_missing_gtk_raises_friendly_503(db_session, project_with_review, monkeypatch):
    """GTK 缺失 → ServiceUnavailableError（503），不裸 500。"""
    p, rec = project_with_review

    class _BrokenHTML:
        def __init__(self, *a, **kw):
            raise OSError("cannot load library 'libgobject-2.0-0': error 0x7e")

    mod = types.ModuleType("weasyprint")
    mod.HTML = _BrokenHTML
    monkeypatch.setitem(sys.modules, "weasyprint", mod)

    from app.services.review_export_service import export_review_report
    with pytest.raises(ServiceUnavailableError, match="GTK"):
        export_review_report(db_session, project=p, review=rec)


def test_export_renders_pdf_and_content(db_session, project_with_review, monkeypatch):
    """正常路径：weasyprint 可用时产出 PDF 字节，报告 HTML 含关键内容。"""
    p, rec = project_with_review

    captured = {}

    class _FakeHTML:
        def __init__(self, *, string):
            captured["html"] = string

        def write_pdf(self):
            return b"%PDF-1.4 fake-bytes"

    mod = types.ModuleType("weasyprint")
    mod.HTML = _FakeHTML
    monkeypatch.setitem(sys.modules, "weasyprint", mod)

    from app.services.review_export_service import export_review_report
    pdf = export_review_report(db_session, project=p, review=rec)

    assert pdf == b"%PDF-1.4 fake-bytes"
    html = captured["html"]
    assert "导出测试项目" in html
    assert "总分 75" in html
    assert "新颖性" in html


def test_export_pdf_header_ascii_safe(client, db_session, project_with_review, monkeypatch):
    """Content-Disposition 必须 latin-1 安全（回归：中文文件名裸放响应头）。

    Starlette 对 header 值 encode("latin-1")，中文 → UnicodeEncodeError → 500，
    即 weasyprint 正常的生产环境导出必坏。修法：filename* 按 RFC 5987
    percent-encode，另给 ASCII 回退 filename。
    """
    import urllib.parse as _up

    p, rec = project_with_review

    class _FakeHTML:
        def __init__(self, *, string):
            pass

        def write_pdf(self):
            return b"%PDF-1.4 fake-bytes"

    mod = types.ModuleType("weasyprint")
    mod.HTML = _FakeHTML
    monkeypatch.setitem(sys.modules, "weasyprint", mod)

    res = client.post(
        "/api/v1/auth/login", json={"username": "export_test", "password": "Pass1234!"}
    )
    assert res.status_code == 200, res.text

    resp = client.get(f"/api/v1/projects/{p.id}/reviews/{rec.id}/export-pdf")
    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    # 原文必须 percent-encode（raw header 不含中文），ASCII 回退名存在
    assert "审查报告" not in cd
    assert 'filename="review-round-1.pdf"' in cd
    assert "审查报告-第1轮.pdf" in _up.unquote(cd)
