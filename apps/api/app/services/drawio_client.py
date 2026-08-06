"""drawio 渲染客户端：调自建 drawio 渲染微服务把 XML 导出为 PNG。

微服务（apps/drawio-render/，端口 8001）跑 draw.io desktop headless CLI（xvfb +
Chromium），提供 POST /render 端点，输入 drawio XML 返回图片字节。

与 app/rag/nli.py 的对称差异：NLI 是软依赖且 fail-open（挂了降级 neutral 走合并，
绝不误删）；drawio 渲染是软依赖但 **fail-closed**——服务不可用/超时/异常一律抛
ServiceUnavailableError，不降级、不留半成品。原因：figure 生成是一次性原子操作，
渲染失败就没有可交付的图，必须让用户重试，而不是存一个空壳 Figure 记录。
"""
import httpx

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError


def render(xml: str, *, fmt: str = "png", scale: int = 2, embed: bool = True) -> bytes:
    """调 drawio 渲染服务把 XML 导出为图片字节。

    参数：
        xml: drawio 图 XML（<mxfile>...</mxfile> 或 <mxGraphModel>...）
        fmt: 导出格式 png/svg/pdf/jpg（默认 png）
        scale: 缩放倍率（PNG/JPG，默认 2，专利附图需要清晰度）
        embed: 是否嵌入 XML（-e，默认 True，导出文件可回 draw.io 编辑）

    返回：图片字节。

    异常：服务不可用/超时/HTTP 错误 → ServiceUnavailableError（fail-closed）。
    """
    base_url = get_settings().drawio_base_url
    try:
        resp = httpx.post(
            f"{base_url}/render",
            json={"xml": xml, "format": fmt, "scale": scale, "embed": embed},
            timeout=120.0,  # Chromium 渲染含冷启可能 10-60s；留足余量
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise ServiceUnavailableError(
            "附图渲染服务暂不可用，请稍后重试"
        ) from e
