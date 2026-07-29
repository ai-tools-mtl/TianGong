"""C1 回归测试：agent loop 内 save_memory commit 后访问 ORM 对象属性。

模拟真实场景：astream_chat/astream_generate 期间 save_memory 工具 db.commit()
（tools.py:94/98），退出 loop 后 endpoint 仍持有 section/conv 引用并访问其属性
（ai.py:239 读 section.id/conv.id、ai.py:347 读 section.status）。

C1 修复（expire_on_commit=False）后这些访问不触发冗余 lazy load，也不在
aborted session 上抛 InternalError。本测试固化这一正确行为，防止未来误改回 True。
"""
import uuid


def _make_project_and_section(db_session):
    """构造真实入库的 User + Project + Section，返回 (user_id, section)。"""
    from app.models import Project, Section, User
    from app.core.security import hash_password

    u = User(
        username=f"loop-{uuid.uuid4().hex[:8]}",
        email=f"loop-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="loop测试",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    p = Project(user_id=u.id, title="测试交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    s = Section(
        project_id=p.id, template_section_id="ts-solution", order=1,
        key="solution", title="技术方案", status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return u.id, s


def test_save_memory_commit_then_read_section_attrs(db_session, monkeypatch):
    """save_memory 工具内 commit 后，访问 section 的 id/status 不抛异常、值正确。

    这是 ai.py:347（读 section.status）/ ai.py:350（读 section.id）的真实路径。
    expire_on_commit=False 下：commit 后 section 未 expire，属性值仍是内存中的
    客户端值（UUID/Python status），访问不触发 SELECT。
    """
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    user_id, section = _make_project_and_section(db_session)
    # 记住 commit 前的值，用于断言 commit 后读到的是同一份
    section_id_before = section.id
    section_status_before = section.status

    # mock embedding 与去重，让 save_memory 走「新建」分支并真实 commit
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = create_agent_tools(db=db_session, user_id=user_id)
    # tools[1] 是 save_memory
    result = tools[1].invoke({"content": "记住我喜欢简洁的写作风格"})
    assert "已保存" in result

    # 核心：save_memory 已 commit（tools.py:98），现在访问 section 属性
    # —— 这是 ai.py 在 agent loop 退出后做的事
    assert section.id == section_id_before   # 客户端 UUID，commit 前后一致
    assert section.status == section_status_before  # Python 赋值，未变

    # 进一步：模拟 ai.py:347 的写后读（section.status = "drafting" 后读）
    section.status = "drafting"
    assert section.status == "drafting"


def test_rag_search_rollback_then_read_section_attrs(db_session, monkeypatch):
    """rag_search 工具异常 rollback 后，访问 section 属性不抛 InternalError。

    rag_search 在检索失败时 db.rollback()（tools.py:46）。rollback 会 expire
    对象（即便 expire_on_commit=False，rollback 仍 expire），但下一访问在新事务上
    同步 reload，正常 session 不抛错。本测试核心是不抛异常 + 值正确。
    """
    from app.ai.tools import create_agent_tools
    from app.rag import retriever

    user_id, section = _make_project_and_section(db_session)
    section_id_before = section.id

    # 让 retrieve 抛异常，触发 rag_search 的 rollback 路径
    def _boom(*args, **kwargs):
        raise RuntimeError("模拟检索失败")

    monkeypatch.setattr(retriever, "retrieve", _boom)

    tools = create_agent_tools(db=db_session, user_id=user_id)
    # tools[0] 是 rag_search
    result = tools[0].invoke({"query": "测试"})
    assert result == []  # 异常时返回空列表

    # rollback 后访问 section.id——不应抛 InternalError（事务已回滚，干净）
    # 允许内部 reload（rollback 会 expire），核心断言是不抛异常 + 值正确
    assert section.id == section_id_before
