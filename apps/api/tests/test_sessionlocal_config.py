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
        "SessionLocal 必须设 expire_on_commit=False（C1 修复）。\n"
        "见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md"
    )


def _count_selects(engine, session):
    """用 event listener 计数 commit 后访问属性触发的 SELECT 次数。

    返回一个闭包，调用它会在「commit 后访问属性」期间计数。
    """
    count = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _counter(conn, cursor, statement, params, context, executemany):
        # 只数 SELECT（lazy load 发的是 SELECT），排除 INSERT
        if statement.lstrip().lower().startswith("select"):
            count["n"] += 1

    return count, _counter


def _make_user(session):
    """构造并提交一个 User，返回该对象（commit 后仍 attached）。"""
    from app.core.security import hash_password
    from app.models import User

    u = User(
        username="expiretest",
        email="expiretest@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="过期测试",
    )
    session.add(u)
    session.commit()
    return u


def test_no_lazy_load_after_commit_when_expire_off(engine):
    """expire_on_commit=False 时，commit 后访问属性不触发额外 SELECT。"""
    from sqlalchemy.orm import sessionmaker

    # 测试内自建 session，显式 expire_on_commit=False（模拟生产配置）
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        count, listener = _count_selects(engine, session)
        u = _make_user(session)
        baseline = count["n"]

        # commit 后访问属性——expire_on_commit=False 下不应触发 lazy load
        _ = u.username
        _ = u.email

        session.in_transaction()  # noop，确保 session 仍可用
        accessed = count["n"] - baseline
        assert accessed == 0, f"expire_on_commit=False 下访问属性不应触发 SELECT，实际触发了 {accessed} 次"
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        session.close()


def test_lazy_load_does_trigger_when_expire_on(engine):
    """对照组：expire_on_commit=True 时，commit 后访问属性会触发 SELECT。

    证明上面那个测试不是「永远 0」的假绿——True 配置下确实 >0。
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, expire_on_commit=True)
    session = Session()
    try:
        count, listener = _count_selects(engine, session)
        u = _make_user(session)
        baseline = count["n"]

        _ = u.username  # expire 了，触发 lazy reload

        accessed = count["n"] - baseline
        assert accessed > 0, "expire_on_commit=True 下访问属性应触发 SELECT（对照组）"
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        session.close()


def test_client_uuid_pk_readable_after_commit(engine):
    """客户端生成的 UUID 主键，commit 后仍可读（ai.py 依赖此行为）。

    ai.py:239/254 等在 commit 后读 section.id/conv.id（均为 default=uuid.uuid4）。
    本测试确认 expire_on_commit=False 下这些读取安全。

    注：SQLAlchemy 的 default=uuid.uuid4 在 flush（INSERT）时才求值，而非对象构造时。
    故先 flush 让 PK 物化，再 commit，验证 commit 后 PK 值不变且类型正确。
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        import uuid
        from app.models import User

        u = User(
            username="pktest", email="pktest@tiangong.dev",
            password_hash="x", name="pk测试",
        )
        session.add(u)
        session.flush()  # 触发 INSERT，default=uuid.uuid4 此刻求值
        pk_before = u.id  # flush 后 PK 已物化，commit 前的值
        session.commit()

        # commit 后读 PK——应等于 commit 前的值，不报错
        assert u.id == pk_before
        assert isinstance(u.id, uuid.UUID)
    finally:
        session.close()
