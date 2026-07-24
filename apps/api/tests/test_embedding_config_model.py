"""UserEmbeddingConfig 表模型测试。"""

import uuid

from app.models import UserEmbeddingConfig, Base


def test_model_imported():
    """UserEmbeddingConfig 可从 app.models 导入（确认 __init__ 导出）。"""
    assert UserEmbeddingConfig is not None


def test_model_in_metadata():
    """表注册在 Base.metadata（conftest 建表依赖此）。"""
    assert "user_embedding_configs" in Base.metadata.tables


def test_model_columns(db_session, registered_user):
    """可插入并读回一条 embedding 配置（覆盖所有列）。"""
    from app.core.security import encrypt_value
    cfg = UserEmbeddingConfig(
        user_id=uuid.UUID(registered_user["id"]),
        name="智谱 embedding",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_encrypted=encrypt_value("sk-test-1234567890"),
        model="embedding-3",
    )
    db_session.add(cfg)
    db_session.commit()
    db_session.refresh(cfg)
    assert cfg.id is not None
    assert cfg.name == "智谱 embedding"
    assert cfg.model == "embedding-3"
    assert cfg.user_id is not None
    assert cfg.created_at is not None
