from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.deps import require_admin
from app.models import User


def _make_admin_app():
    """临时 app，含一个仅 admin 可访问的路由。"""
    app = FastAPI()

    # 注册异常处理器（否则 AppError 返回 500 而非 403）
    from app.core.exceptions import register_exception_handlers
    register_exception_handlers(app)

    @app.get("/admin-only")
    def admin_only_route(admin: User = Depends(require_admin)):
        return {"id": str(admin.id)}

    return app


def test_admin_can_access(client, db_session):
    admin = User(
        email="admin@example.com",
        password_hash=hash_password("Pass1234!"),
        name="管理员",
        role="admin",
    )
    db_session.add(admin)
    db_session.commit()

    app = _make_admin_app()
    # 复用 client 的 get_db override（通过共享 engine）
    from app.core.database import get_db
    from sqlalchemy.orm import sessionmaker
    TestingSession = sessionmaker(bind=db_session.bind)
    app.dependency_overrides[get_db] = lambda: (yield TestingSession())

    with TestClient(app) as c:
        token = create_access_token({"sub": str(admin.id), "role": "admin"})
        c.cookies.set("access_token", token)
        res = c.get("/admin-only")
        assert res.status_code == 200


def test_normal_user_forbidden(client, db_session, registered_user):
    app = _make_admin_app()
    from app.core.database import get_db
    from sqlalchemy.orm import sessionmaker
    TestingSession = sessionmaker(bind=db_session.bind)
    app.dependency_overrides[get_db] = lambda: (yield TestingSession())

    with TestClient(app) as c:
        token = create_access_token({"sub": registered_user["id"], "role": "user"})
        c.cookies.set("access_token", token)
        res = c.get("/admin-only")
        assert res.status_code == 403
