"""drawio 渲染客户端测试。

fail-closed 语义：服务不可用/超时/HTTP 错误一律抛 ServiceUnavailableError（不降级），
与 nli.judge_relation 的 fail-open（降级 neutral）相反——figure 生成是原子操作，
渲染失败就没有可交付物，必须让用户重试。
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.exceptions import ServiceUnavailableError


def _fake_png() -> MagicMock:
    """构造渲染服务的成功响应：返回 PNG 字节。"""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    return resp


def test_render_success():
    """成功渲染返回 PNG 字节。"""
    from app.services import drawio_client

    with patch("app.services.drawio_client.httpx.post", return_value=_fake_png()):
        png = drawio_client.render("<mxfile/>")

    assert png.startswith(b"\x89PNG")


def test_render_service_down_raises():
    """服务挂掉，抛 ServiceUnavailableError（fail-closed）。"""
    from app.services import drawio_client

    with patch("app.services.drawio_client.httpx.post", side_effect=Exception("connection refused")):
        with pytest.raises(ServiceUnavailableError):
            drawio_client.render("<mxfile/>")


def test_render_timeout_raises():
    """超时，抛 ServiceUnavailableError。"""
    from app.services import drawio_client

    with patch("app.services.drawio_client.httpx.post", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(ServiceUnavailableError):
            drawio_client.render("<mxfile/>")


def test_render_http_error_raises():
    """HTTP 5xx，抛 ServiceUnavailableError。"""
    from app.services import drawio_client

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock(),
    )

    with patch("app.services.drawio_client.httpx.post", return_value=fake_resp):
        with pytest.raises(ServiceUnavailableError):
            drawio_client.render("<mxfile/>")


def test_render_passes_format_and_scale():
    """参数透传到请求 body。"""
    from app.services import drawio_client

    with patch("app.services.drawio_client.httpx.post", return_value=_fake_png()) as mock_post:
        drawio_client.render("<mxfile/>", fmt="svg", scale=3, embed=False)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["format"] == "svg"
    assert kwargs["json"]["scale"] == 3
    assert kwargs["json"]["embed"] is False
