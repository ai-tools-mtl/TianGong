"""C1 修复：SessionLocal expire_on_commit 配置与 commit 后不 expire 行为测试。

设计依据见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md。

关键约束（conftest.py）：
- 测试用的 db_session/app_obj fixture 自建 sessionmaker，不引用生产 SessionLocal。
  故「配置生效」必须直接断言生产 SessionLocal，而非通过 fixture 间接验证。
- SQLite 不执行 PG server_default，时间戳类断言在测试层无效，靠 PG 手动验证。
"""
from sqlalchemy import event


def test_sessionlocal_expire_on_commit_is_false():
    """生产 SessionLocal 必须设 expire_on_commit=False（C1 修复的核心断言）。

    断言生产 sessionmaker 的 kwargs，而非 fixture session——后者是 conftest
    独立新建的，不受此配置影响。
    """
    from app.core.database import SessionLocal

    assert SessionLocal.kw["expire_on_commit"] is False, (
        "SessionLocal 必须设 expire_on_commit=False（C1 修复）。"
        "见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md"
    )
