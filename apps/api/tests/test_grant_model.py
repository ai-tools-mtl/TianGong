"""UserGlobalLLMGrant 模型 + UserLLMConfig 多配置测试（阶段 2 地基）。"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import User, UserGlobalLLMGrant, UserLLMConfig


def test_grant_table_importable():
    assert UserGlobalLLMGrant.__tablename__ == "user_global_llm_grants"


def test_grant_create_row(db_session):
    """可插入一条授权记录。"""
    u = User(username="g1", password_hash="x", name="G")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    g = UserGlobalLLMGrant(user_id=u.id)
    db_session.add(g); db_session.commit(); db_session.refresh(g)
    assert g.id is not None
    assert g.revoked_at is None
    assert g.granted_at is not None


def test_grant_user_unique(db_session):
    """一个用户最多一条授权（user_id unique）。"""
    u = User(username="g2", password_hash="x", name="G2")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    db_session.add(UserGlobalLLMGrant(user_id=u.id)); db_session.commit()
    db_session.add(UserGlobalLLMGrant(user_id=u.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_user_can_have_multiple_llm_configs(db_session):
    """UserLLMConfig 去 unique 后，一个用户可有多条配置。"""
    u = User(username="g3", password_hash="x", name="G3")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    db_session.add(UserLLMConfig(user_id=u.id, name="公司Key", provider="custom",
                                 base_url="https://a.com", api_key_encrypted="x",
                                 model="m1", is_active=True))
    db_session.add(UserLLMConfig(user_id=u.id, name="个人Key", provider="custom",
                                 base_url="https://b.com", api_key_encrypted="y",
                                 model="m2", is_active=True))
    db_session.commit()  # 不应抛 IntegrityError（去 unique）
    assert db_session.query(UserLLMConfig).filter_by(user_id=u.id).count() == 2
