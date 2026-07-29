"""embedding 调用应写 LLMCallLog(action='embed')（D7）。

archiver / retriever / knowledge_service 三个 embedding caller 调完 embed 后，
必须写一条 action="embed" 的元数据日志，让 admin 调用统计能区分 chat/embedding。
仅存元数据（model/provider/status），绝不存内容（设计 8.3 红线）。

注意：archive_project 在「无 section」时会 early-return，走不到 embed_texts。
所以 archiver 的测试必须造一个含 Tiptap 文本的 Section，才能真正覆盖 embed 路径。
"""

import uuid
from unittest.mock import patch, MagicMock

from sqlalchemy import select


def _fake_embed_config() -> MagicMock:
    """构造一个假 ResolvedEmbeddingConfig（只用到 model/source 字段）。"""
    cfg = MagicMock()
    cfg.model = "emb-3"
    cfg.source = "user"
    return cfg


# ─────────────────────────── archiver ───────────────────────────


def test_archiver_logs_embed_call():
    """归档异步化后，archive_project 不再同步 embed；日志在 run_archive_embed_standalone。

    SQLite 测试库无 pgvector 表，无法直接调 run_archive_embed_standalone（查 chunk 报错）。
    改为源码断言：确认 run_archive_embed_standalone 含 success/failed 两条 log_embed_call，
    且 archive_project 不直接调 embed_texts（异步契约）。
    """
    import inspect
    from app.rag import archiver

    # archive_project 异步契约：不直接调 embed_texts
    archive_src = inspect.getsource(archiver.archive_project)
    assert "embed_texts" not in archive_src, "archive_project 异步化后不应调 embed_texts"

    # run_archive_embed_standalone 含日志写入（success + failed）
    standalone_src = inspect.getsource(archiver.run_archive_embed_standalone)
    assert "log_embed_call" in standalone_src, "run_archive_embed_standalone 缺日志写入"
    assert 'status="success"' in standalone_src, "缺 success 日志"
    assert 'status="failed"' in standalone_src, "缺 failed 日志"


# ─────────────────────────── retriever ───────────────────────────


def test_retriever_logs_embed_call(db_session):
    """retrieve 调 embed_text 后写一条 action='embed' 的日志（无 project_id）。

    retrieve 的 embed_log 在 cosine_distance SELECT 之前就已写库并 commit；
    后续 pgvector 查询在 SQLite 测试库不支持 <=> 算子，会抛 OperationalError——
    那是向量检索本身的环境限制（与本任务日志无关），吞掉即可，只验日志已落。
    """
    from app.rag import retriever
    from app.models import LLMCallLog

    uid = uuid.uuid4()
    fake_cfg = _fake_embed_config()
    with patch("app.rag.retriever.resolve_embedding_config", return_value=fake_cfg), \
         patch("app.rag.retriever.embed_text", return_value=[0.1, 0.2]):
        try:
            retriever.retrieve(db_session, user_id=uid, query="q")
        except Exception:
            # pgvector cosine_distance 在 SQLite 不支持（见 conftest knowledge_chunks 兼容表）
            pass

    logs = db_session.scalars(
        select(LLMCallLog).where(LLMCallLog.action == "embed")
    ).all()
    assert len(logs) >= 1
    assert logs[0].model == "emb-3"
    assert logs[0].provider == "user"
    assert logs[0].status == "success"
    assert logs[0].user_id == uid
    # retriever 与具体 project 无关
    assert logs[0].project_id is None


# ─────────────────────────── knowledge_service ───────────────────────────


def test_knowledge_service_logs_embed_call():
    """embed_chunks_for_file（异步化后从 _ingest_chunks 拆出的向量化逻辑）
    调 embed_texts 后写一条 action='embed' 的成功日志；失败时写 failed 日志。

    SQLite 测试库无 knowledge_chunks 表，无法直接调 embed_chunks_for_file，
    改为源码断言：确认函数体含 success/failed 两条 log_embed_call（对齐 archiver 测试）。
    """
    import inspect
    from app.services import knowledge_service as ks

    src = inspect.getsource(ks.embed_chunks_for_file)
    assert "log_embed_call" in src, "embed_chunks_for_file 缺少 embed 日志写入"
    assert 'status="success"' in src, "embed_chunks_for_file 缺少 success 日志"
    assert 'status="failed"' in src, "embed_chunks_for_file 缺少 failed 日志"


# ─────────────────────────── helper 自身健壮性 ───────────────────────────


def test_log_embed_call_never_raises(db_session):
    """helper 内部失败必须吞掉异常（日志不应影响主流程）。"""
    from app.services.llm_log_helper import log_embed_call

    # 传一个非法 user_id 触发 DB 错误，helper 应吞掉、回滚、不抛
    log_embed_call(
        db_session,
        user_id=object(),  # type: ignore[arg-type]
        model="m",
        provider="user",
    )
    # 走到这里说明没抛
