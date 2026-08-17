# apps/api/tests/test_terms_api.py
"""项目术语表（T2 批3）：CRUD + AI 抽取候选 + 一致性检查（规则+LLM 双路）。

spec：docs/superpowers/specs/2026-08-17-advice-revision-loop-design.md §3.3
- project_terms 表：term/definition/variants(JSONB)/enabled/source，unique(project_id, term)
- extract：lite 模型抽候选（不入库，返回列表），失败降级空+warning（照抄 outline_extractor 先例）
- check：规则路（variants 子串扫描，零 token，提示性质含复合词误报）+
  LLM 路（表外漂移建议，fail-open）+ 可选 llm_verify 复核
"""
import uuid

import pytest


def _login(client, user):
    client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "Pass1234!"})


@pytest.fixture
def terms_user(db_session):
    from app.core.security import hash_password
    from app.models import User
    u = User(
        username=f"tm-{uuid.uuid4().hex[:6]}",
        email=f"tm-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="术语用户",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def other_user(db_session):
    from app.core.security import hash_password
    from app.models import User
    u = User(
        username=f"to-{uuid.uuid4().hex[:6]}",
        email=f"to-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="他人",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def project(db_session, terms_user):
    from app.models import Project
    p = Project(user_id=terms_user.id, title="术语表测试项目")
    db_session.add(p)
    db_session.commit()
    return p


def _mk_section(db_session, project, key, title, text):
    from app.models import Section
    s = Section(
        project_id=project.id, template_section_id=key, key=key,
        title=title, order=1, status="drafting",
        content={"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ]},
    )
    db_session.add(s)
    db_session.commit()
    return s


class TestTermsCRUD:
    def test_create_list(self, client, db_session, terms_user, project):
        _login(client, terms_user)
        res = client.post(f"/api/v1/projects/{project.id}/terms", json={
            "term": "处理模块", "definition": "核心计算单元",
            "variants": ["单元", "处理单元"],
        })
        assert res.status_code == 200, res.text
        created = res.json()
        assert created["term"] == "处理模块"
        assert created["variants"] == ["单元", "处理单元"]
        assert created["enabled"] is True
        assert created["source"] == "manual"

        res2 = client.get(f"/api/v1/projects/{project.id}/terms")
        assert res2.status_code == 200
        items = res2.json()
        assert len(items) == 1 and items[0]["term"] == "处理模块"

    def test_unique_conflict_409(self, client, db_session, terms_user, project):
        _login(client, terms_user)
        client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "处理模块"})
        res = client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "处理模块"})
        assert res.status_code == 409

    def test_isolation_other_users_project_404(self, client, db_session, terms_user, other_user, project):
        _login(client, other_user)
        res = client.get(f"/api/v1/projects/{project.id}/terms")
        assert res.status_code == 404
        res = client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "x"})
        assert res.status_code == 404

    def test_update_partial_and_enabled_toggle(self, client, db_session, terms_user, project):
        _login(client, terms_user)
        created = client.post(f"/api/v1/projects/{project.id}/terms", json={
            "term": "处理模块", "variants": ["单元"]}).json()
        res = client.put(f"/api/v1/terms/{created['id']}", json={"enabled": False})
        assert res.status_code == 200
        assert res.json()["enabled"] is False
        assert res.json()["variants"] == ["单元"]  # 未传字段不变
        res = client.put(f"/api/v1/terms/{created['id']}", json={"variants": ["单元", "部件"]})
        assert res.json()["variants"] == ["单元", "部件"]

    def test_isolation_other_users_term_404(self, client, db_session, terms_user, other_user, project):
        _login(client, terms_user)
        created = client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "处理模块"}).json()
        _login(client, other_user)
        res = client.put(f"/api/v1/terms/{created['id']}", json={"enabled": False})
        assert res.status_code == 404
        res = client.delete(f"/api/v1/terms/{created['id']}")
        assert res.status_code == 404

    def test_delete(self, client, db_session, terms_user, project):
        _login(client, terms_user)
        created = client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "处理模块"}).json()
        res = client.delete(f"/api/v1/terms/{created['id']}")
        assert res.status_code == 200
        assert client.get(f"/api/v1/projects/{project.id}/terms").json() == []


# ── 规则扫描纯函数 ────────────────────────────────────────────────────────────

class TestRuleScan:
    def test_scan_finds_variants_across_sections(self, db_session, project):
        from app.services.term_service import scan_variants
        _mk_section(db_session, project, "problem", "技术问题", "本系统的处理模块存在单元失效问题")
        _mk_section(db_session, project, "solution", "技术方案", "处理模块包含存储单元与控制单元")
        issues = scan_variants(
            [{"term": "处理模块", "variants": ["单元", "部件"]}],
            section_texts={"技术问题": "本系统的处理模块存在单元失效问题",
                           "技术方案": "处理模块包含存储单元与控制单元"},
            key_map={"技术问题": "problem", "技术方案": "solution"},
        )
        # 「单元」在两章共命中 3 次（「单元失效」1 + 「存储单元」「控制单元」2）
        by_variant = {(i["term"], i["variant"]): i for i in issues}
        assert ("处理模块", "单元") in by_variant
        unit = by_variant[("处理模块", "单元")]
        assert unit["count"] == 3
        assert set(unit["section_keys"]) == {"problem", "solution"}
        assert ("处理模块", "部件") not in by_variant

    def test_scan_compound_word_hits(self):
        """复合词命中（「存储单元」含「单元」）——误报定性：断言命中而非漏报（D10）。"""
        from app.services.term_service import scan_variants
        issues = scan_variants(
            [{"term": "处理模块", "variants": ["单元"]}],
            section_texts={"技术方案": "包含存储单元"},
            key_map={"技术方案": "solution"},
        )
        assert len(issues) == 1 and issues[0]["count"] == 1

    def test_scan_skips_disabled(self):
        from app.services.term_service import scan_variants
        issues = scan_variants(
            [{"term": "处理模块", "variants": ["单元"], "enabled": False}],
            section_texts={"A": "单元"},
            key_map={"A": "a"},
        )
        assert issues == []


# ── extract / check 端点 ─────────────────────────────────────────────────────

def _mock_llm(monkeypatch, content: str):
    """mock term_service 的 get_llm：invoke 返回固定文本（容错 JSON 解析输入）。"""
    from unittest.mock import MagicMock
    from app.services import term_service
    mock_llm = MagicMock()
    resp = MagicMock()
    resp.content = content
    mock_llm.invoke.return_value = resp
    monkeypatch.setattr(term_service, "get_llm", lambda cfg: mock_llm)
    return mock_llm


class TestExtract:
    def test_success_returns_candidates(self, client, db_session, terms_user, project, monkeypatch):
        _mk_section(db_session, project, "solution", "技术方案", "处理模块负责数据调度，控制单元负责时序")
        _mock_llm(monkeypatch, '{"candidates": [{"term": "处理模块", "definition": "核心单元", "variants": ["处理单元"], "occurrences": 5}]}')
        _login(client, terms_user)
        res = client.post(f"/api/v1/projects/{project.id}/terms/extract")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["candidates"][0]["term"] == "处理模块"
        assert data["candidates"][0]["variants"] == ["处理单元"]

    def test_llm_failure_degrades_empty(self, client, db_session, terms_user, project, monkeypatch):
        """LLM 失败/输出不合法 → 200 + 空候选 + warning（不阻断，照抄 outline 先例）。"""
        _mk_section(db_session, project, "solution", "技术方案", "正文")
        _mock_llm(monkeypatch, "这不是 JSON")
        _login(client, terms_user)
        res = client.post(f"/api/v1/projects/{project.id}/terms/extract")
        assert res.status_code == 200
        assert res.json()["candidates"] == []
        assert "warning" in res.json()

    def test_empty_project_409(self, client, db_session, terms_user, project):
        _login(client, terms_user)
        res = client.post(f"/api/v1/projects/{project.id}/terms/extract")
        assert res.status_code == 409


class TestCheck:
    def test_empty_terms_skips_llm(self, client, db_session, terms_user, project, monkeypatch):
        from unittest.mock import MagicMock
        from app.services import term_service
        called = MagicMock()
        monkeypatch.setattr(term_service, "get_llm", called)  # 不应被调用
        _login(client, terms_user)
        res = client.post(f"/api/v1/projects/{project.id}/terms/check", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["rule_issues"] == [] and data["llm_suggestions"] == []
        called.assert_not_called()

    def test_rule_issues_reported(self, client, db_session, terms_user, project):
        _mk_section(db_session, project, "solution", "技术方案", "控制单元负责时序")
        _login(client, terms_user)
        client.post(f"/api/v1/projects/{project.id}/terms",
                    json={"term": "控制模块", "variants": ["控制单元"]})
        res = client.post(f"/api/v1/projects/{project.id}/terms/check", json={})
        assert res.status_code == 200
        rule = res.json()["rule_issues"]
        assert len(rule) == 1
        assert rule[0]["term"] == "控制模块" and rule[0]["variant"] == "控制单元"
        assert rule[0]["count"] == 1

    def test_llm_drift_suggestions(self, client, db_session, terms_user, project, monkeypatch):
        """LLM 路发现表外漂移（同概念多种说法但均未登记）。"""
        _mk_section(db_session, project, "solution", "技术方案", "服务器与主机进行通信")
        _login(client, terms_user)
        client.post(f"/api/v1/projects/{project.id}/terms", json={"term": "控制模块"})
        _mock_llm(monkeypatch, '{"drifts": [{"concept": "服务器", "variants": ["主机"], "section_keys": ["solution"]}]}')
        res = client.post(f"/api/v1/projects/{project.id}/terms/check", json={})
        assert res.status_code == 200
        drifts = res.json()["llm_suggestions"]
        assert drifts and drifts[0]["concept"] == "服务器"

    def test_llm_failure_fail_open(self, client, db_session, terms_user, project, monkeypatch):
        """LLM 失败 → llm_suggestions 空列表 + warning，rule_issues 照常返回。"""
        _mk_section(db_session, project, "solution", "技术方案", "控制单元负责时序")
        _login(client, terms_user)
        client.post(f"/api/v1/projects/{project.id}/terms",
                    json={"term": "控制模块", "variants": ["控制单元"]})
        _mock_llm(monkeypatch, "垃圾输出")
        res = client.post(f"/api/v1/projects/{project.id}/terms/check", json={})
        assert res.status_code == 200
        data = res.json()
        assert len(data["rule_issues"]) == 1  # 规则路不受影响
        assert data["llm_suggestions"] == []
        assert "warning" in data

    def test_llm_verify_filters_false_positive(self, client, db_session, terms_user, project, monkeypatch):
        """llm_verify 复核：LLM 判复合词误报为假阳性 → verified=False（D10）。"""
        from unittest.mock import MagicMock
        from app.services import term_service

        _mk_section(db_session, project, "solution", "技术方案", "包含存储单元")
        _login(client, terms_user)
        client.post(f"/api/v1/projects/{project.id}/terms",
                    json={"term": "处理模块", "variants": ["单元"]})

        mock_llm = MagicMock()
        # 两次 invoke：① 漂移检测（无漂移）② 误报复核（判 index 0 为误用真阳性？
        #   「存储单元」中的「单元」不是「处理模块」的误用 → verified False）
        drift_resp = MagicMock(); drift_resp.content = '{"drifts": []}'
        verify_resp = MagicMock(); verify_resp.content = '{"results": [{"index": 0, "verified": false}]}'
        mock_llm.invoke.side_effect = [drift_resp, verify_resp]
        monkeypatch.setattr(term_service, "get_llm", lambda cfg: mock_llm)

        res = client.post(f"/api/v1/projects/{project.id}/terms/check",
                          json={"llm_verify": True})
        assert res.status_code == 200
        rule = res.json()["rule_issues"]
        assert len(rule) == 1
        assert rule[0]["verified"] is False  # 复核判误报（前端可置灰展示）


# ── 术语注入层（context_assembler，T2 spec §3.3.3）────────────────────────────

class TestTermsInjection:
    def _build_ctx(self, db_session, project, terms):
        """建 terms 后调 build_system_prompt，返回 prompt 字符串。"""
        from app.ai.context_assembler import build_system_prompt
        from app.models import ProjectTerm
        for spec in terms:
            db_session.add(ProjectTerm(project_id=project.id, **spec))
        db_session.commit()
        return build_system_prompt(db_session, _mk_section(
            db_session, project, "solution", "技术方案", "正文"))

    def test_enabled_terms_injected_with_format(self, db_session, terms_user, project):
        prompt = self._build_ctx(db_session, project, [
            {"term": "处理模块", "definition": "核心计算单元",
             "variants": ["单元", "处理单元"]},
            {"term": "控制器", "variants": []},
        ])
        assert "# 本项目术语表（写作与修订必须使用标准术语，禁止使用其变体）" in prompt
        assert "- 处理模块（禁用：单元、处理单元）：核心计算单元" in prompt
        assert "- 控制器" in prompt

    def test_disabled_not_injected(self, db_session, terms_user, project):
        prompt = self._build_ctx(db_session, project, [
            {"term": "处理模块", "enabled": False, "variants": ["单元"]},
        ])
        assert "本项目术语表" not in prompt  # 整层跳过

    def test_position_between_written_and_rag(self, db_session, terms_user, project):
        """注入位置：已写章节层之后、知识库 RAG 层之前（spec §3.3.3）。"""
        # 额外建一个章节让「已完成章节内容」前文层出现（solution 是当前章节被 exclude）
        _mk_section(db_session, project, "problem", "技术问题", "前文内容")
        prompt = self._build_ctx(db_session, project, [{"term": "处理模块"}])
        i_written = prompt.find("# 已完成章节内容")
        i_terms = prompt.find("# 本项目术语表")
        i_rag = prompt.find("# 知识库参考")
        assert i_written != -1 and i_terms != -1
        assert i_written < i_terms
        if i_rag != -1:
            assert i_terms < i_rag

    def test_definition_truncated(self, db_session, terms_user, project):
        prompt = self._build_ctx(db_session, project, [
            {"term": "处理模块", "definition": "字" * 300},
        ])
        assert "字" * 200 in prompt
        assert "字" * 201 not in prompt

    def test_read_failure_silent(self, db_session, terms_user, project, monkeypatch):
        """术语读取失败静默降级（不炸整体装配，与其他层一致）。"""
        from app.ai import context_assembler as ca
        _mk_section(db_session, project, "solution", "技术方案", "正文")
        monkeypatch.setattr(ca, "_project_terms_lines",
                            lambda db, pid: (_ for _ in ()).throw(RuntimeError("db boom")))
        prompt = ca.build_system_prompt(db_session, _get_section(db_session, project))
        assert "技术方案" in prompt  # 装配仍完成

    def test_over_limit_truncated(self, db_session, terms_user, project):
        from app.models import ProjectTerm
        for i in range(105):
            db_session.add(ProjectTerm(project_id=project.id, term=f"术语{i:03d}"))
        db_session.commit()
        from app.ai.context_assembler import _project_terms_lines
        lines = _project_terms_lines(db_session, project.id)
        # 标题行 1 + 条目 100 = 101
        assert len(lines) == 101


def _get_section(db_session, project):
    from sqlalchemy import select
    from app.models import Section
    return db_session.scalar(select(Section).where(Section.project_id == project.id))
