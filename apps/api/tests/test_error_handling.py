def test_not_found_returns_404(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "not_found"


def test_unauthorized_returns_401_without_detail(client):
    res = client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_validation_error_returns_422(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    # 空标题违反 min_length
    res = client.post("/api/v1/projects", json={"title": ""})
    assert res.status_code == 422


def test_validation_error_logged_with_details(client, registered_user):
    """422 校验失败：服务端日志带字段错误细节（排障盲区修复）。"""
    from loguru import logger as loguru_logger

    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    messages = []
    sink_id = loguru_logger.add(lambda m: messages.append(m), format="{message}")
    try:
        res = client.post("/api/v1/projects", json={"title": ""})
    finally:
        loguru_logger.remove(sink_id)
    assert res.status_code == 422
    # 响应体保持 FastAPI 默认 {detail: [...]} 结构（前端兼容）
    assert isinstance(res.json()["detail"], list)
    # 日志含「参数校验失败」且带字段名（loguru dict 参数会格式化进消息）
    joined = "".join(messages)
    assert "参数校验失败" in joined
    assert "title" in joined
