# apps/api/tests/test_init_generate_rag.py
"""init generate 链路 RAG 注入测试。

测 _build_section_generate_messages 在 db + user_id 提供时，会检索知识库并把命中片段
注入为 SystemMessage；检索失败/无命中时静默跳过（不阻断生成）。

策略：
- mock compress_history（避免触发真实 LLM 压缩，直接返回空历史 + 未触发 snapshot）
- mock rag.retriever.retrieve（控制命中/空/抛异常三种场景）
- 直接调 _build_section_generate_messages，断言返回 messages 里是否含 RAG SystemMessage

项目无 async 测试先例，沿用 asyncio.run() 同步风格（参考 test_orchestrator.py）。
"""
import asyncio
import uuid
from unittest.mock import MagicMock


def _make_section():
    """构造一个内存 Section（不入库，仅提供 .title/.key 给装配函数）。"""
    s = MagicMock()
    s.title = "技术方案"
    s.key = "solution"
    return s


def _patch_compress_noop(monkeypatch):
    """mock compress_history 为未触发空压缩（避免真实 LLM 调用）。

    compress_history 在 _build_section_generate_messages 内是函数级 import
    （from app.ai.context_compactor import compress_history），故 patch 源模块。
    """
    from app.ai import context_compactor as cc_mod

    async def _noop(history, current_input, llm_config, *, scene=None):
        snapshot = MagicMock()
        snapshot.triggered = False
        snapshot.to_dict.return_value = {}
        return [], snapshot

    monkeypatch.setattr(cc_mod, "compress_history", _noop)


def _patch_retrieve(monkeypatch, *, results=None, raise_exc=None):
    """mock rag.retriever.retrieve：返回指定结果 / 抛异常。

    results=None 且 raise_exc=None → 模拟无命中（返回空列表）。
    """
    from app.rag import retriever as ret_mod

    if raise_exc is not None:
        def _retrieve(db, *, user_id, query, top_k=3, scope=None):
            raise raise_exc
    else:
        def _retrieve(db, *, user_id, query, top_k=3, scope=None):
            return results or []

    monkeypatch.setattr(ret_mod, "retrieve", _retrieve)


def test_rag_snippet_injected_when_hits(monkeypatch, db_session):
    """知识库命中时，messages 含 RAG 参考片段 SystemMessage。"""
    from app.ai.init_orchestrator import _build_section_generate_messages
    from app.rag.retriever import RetrievalResult

    _patch_compress_noop(monkeypatch)
    _patch_retrieve(monkeypatch, results=[
        RetrievalResult(content="电池热失控防护的常见做法是……", score=0.9,
                        source_section_key="solution", project_title="动力电池安全"),
    ])

    # 捕获 retrieve 收到的 query，验证用了 brief + 章节标题
    from app.rag import retriever as ret_mod
    captured_query = {}
    orig_retrieve = ret_mod.retrieve
    def _spy(db, *, user_id, query, top_k=3, scope=None):
        captured_query["query"] = query
        return orig_retrieve(db, user_id=user_id, query=query, top_k=top_k, scope=scope)
    monkeypatch.setattr(ret_mod, "retrieve", _spy)

    messages = asyncio.run(_build_section_generate_messages(
        _make_section(), [], llm_config=MagicMock(),
        outline={"solution": {"content": "本方案采用复合隔热层"}},
        db=db_session, user_id=uuid.uuid4(),
    ))

    # query 应同时含 brief 内容和章节标题
    assert "复合隔热层" in captured_query["query"]
    assert "技术方案" in captured_query["query"]

    # 应存在一条 SystemMessage 含「相关知识库片段」
    rag_msgs = [m for m in messages
                if "相关知识库片段" in getattr(m, "content", "")]
    assert len(rag_msgs) == 1
    assert "电池热失控防护" in rag_msgs[0].content
    assert "动力电池安全" in rag_msgs[0].content


def test_rag_not_injected_when_no_hit(monkeypatch, db_session):
    """知识库无命中时，messages 不含 RAG SystemMessage。"""
    from app.ai.init_orchestrator import _build_section_generate_messages

    _patch_compress_noop(monkeypatch)
    _patch_retrieve(monkeypatch, results=[])  # 无命中

    messages = asyncio.run(_build_section_generate_messages(
        _make_section(), [], llm_config=MagicMock(),
        outline={"solution": {"content": "某技术方案"}},
        db=db_session, user_id=uuid.uuid4(),
    ))

    rag_msgs = [m for m in messages
                if "相关知识库片段" in getattr(m, "content", "")]
    assert len(rag_msgs) == 0


def test_rag_not_injected_when_retrieve_fails(monkeypatch, db_session):
    """检索抛异常时静默降级，不阻断、不注入（与 rag_search 容错语义一致）。"""
    from app.ai.init_orchestrator import _build_section_generate_messages

    _patch_compress_noop(monkeypatch)
    _patch_retrieve(monkeypatch, raise_exc=RuntimeError("embedding 服务不可用"))

    messages = asyncio.run(_build_section_generate_messages(
        _make_section(), [], llm_config=MagicMock(),
        outline={"solution": {"content": "某技术方案"}},
        db=db_session, user_id=uuid.uuid4(),
    ))

    # 检索失败：不注入 RAG 片段，但消息装配正常完成（不抛异常）
    rag_msgs = [m for m in messages
                if "相关知识库片段" in getattr(m, "content", "")]
    assert len(rag_msgs) == 0
    # 仍应有 INIT_GENERATE_SYSTEM_PROMPT 首条 + 生成指令末条（装配未中断）
    assert len(messages) >= 2


def test_rag_not_injected_when_no_db_or_user(monkeypatch, db_session):
    """db/user_id 任一为 None（向后兼容场景）时不检索、不注入。"""
    from app.ai.init_orchestrator import _build_section_generate_messages

    _patch_compress_noop(monkeypatch)
    _patch_retrieve(monkeypatch, results=[
        type("R", (), {"content": "x", "score": 1, "project_title": None,
                       "source_section_key": None})(),
    ])

    # 不传 db / user_id（走默认 None）
    messages = asyncio.run(_build_section_generate_messages(
        _make_section(), [], llm_config=MagicMock(), outline=None,
    ))

    rag_msgs = [m for m in messages
                if "相关知识库片段" in getattr(m, "content", "")]
    assert len(rag_msgs) == 0
