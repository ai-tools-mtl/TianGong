"""drawio 渲染微服务。

用 draw.io desktop 的 headless CLI 把 .drawio XML 导出为 PNG/SVG/PDF。
照 apps/nli 的单文件 FastAPI 范式；差异是「计算资源」是系统级二进制（drawio CLI =
Electron+Chromium）而非模型权重，故需 xvfb 提供虚拟显示器（在 Dockerfile CMD 用
xvfb-run 包裹 uvicorn）。

为何自建而非用 mermaid 等纯文本方案：drawio 支持丰富图形、泳道、精确几何、嵌入可编辑
XML（-e），适合专利附图这种需要清晰标注与可编辑性的场景。CLI 与 drawio-skill 同源，
prompt 与渲染参数知识可直接迁移。

Linux headless 已知坑（drawio-desktop issues + drawio-skill troubleshooting.md）：
- HOME 必须可写，否则 "Home directory not accessible"（Dockerfile 已设 HOME=/tmp）
- --no-sandbox 必须放命令末尾，放前面会被当成输入文件名（drawio-desktop#249,#1056）
- --disable-gpu 抑制无 GPU 环境的 GL/EGL 报错
- xvfb-run 提供 DISPLAY，否则 Chromium 起不来

模块级预热：启动时跑一次空渲染 warm up Chromium，避免首请求承担冷启延迟。
"""
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("drawio-render")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# drawio CLI 二进制名：drawio-desktop .deb 装出来是 drawio。
DRAWIO_BIN = shutil.which("drawio") or "drawio"

# 支持的导出格式 -> (CLI -f 值, media_type)
_FORMATS = {
    "png": ("png", "image/png"),
    "svg": ("svg", "image/svg+xml"),
    "pdf": ("pdf", "application/pdf"),
    "jpg": ("jpg", "image/jpeg"),
}

def _warmup() -> None:
    """预热：跑一次空渲染 warm up Chromium（首次冷启 10-60s）。

    仅记日志，失败不影响服务（首请求会再次冷启，client timeout 已覆盖）。
    """
    minimal = '<mxfile><diagram name="warmup"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>'
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = str(Path(td) / "w.drawio")
            out_path = str(Path(td) / "w.png")
            Path(in_path).write_text(minimal, encoding="utf-8")
            _run_drawio_export(in_path, out_path, "png", scale=1, width=None, embed=False)
        logger.info("drawio 预热完成（首请求将快）")
    except Exception as e:  # noqa: BLE001
        # 预热是优化项非必需：失败只意味着首请求承担 Chromium 冷启延迟（约 10-20s），
        # client timeout 120s 已覆盖。真实渲染经 /render 端点验证可靠，故失败降级为
        # debug 日志，不刷 WARNING 噪声污染容器启动日志。
        logger.debug("drawio 预热失败（首请求将承担冷启延迟，功能不受影响）: %s", e)


def _delayed_warmup() -> None:
    """延迟预热：等 dbus + Xvfb + Chromium 冷启动完成再跑。"""
    import time
    time.sleep(8)
    _warmup()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """启动时在后台线程预热 Chromium，不阻塞 uvicorn 监听（否则 health 永远不通）。"""
    if os.environ.get("DRAWIO_SKIP_WARMUP") != "1":
        threading.Thread(target=_delayed_warmup, daemon=True).start()
    yield


app = FastAPI(title="TianGong drawio Render Service", lifespan=_lifespan)


class RenderRequest(BaseModel):
    """渲染请求：drawio XML + 目标格式。

    scale 仅对 PNG/JPG 生效（SVG/PDF 是矢量）。width 为目标像素宽度（与 scale 互斥）。
    border 为页边距像素（白色留白，对应 drawio CLI -b，专利附图标准要求留白）。
    """
    xml: str = Field(..., min_length=1, description="drawio 图 XML（<mxfile>...</mxfile> 或 <mxGraphModel>...）")
    format: str = Field("png", description="导出格式：png / svg / pdf / jpg")
    scale: int | None = Field(None, ge=1, le=4, description="缩放倍率（PNG/JPG），默认 3≈300DPI")
    width: int | None = Field(None, ge=100, le=4000, description="目标宽度像素（PNG/JPG，与 scale 互斥）")
    embed: bool = Field(True, description="是否嵌入 XML（-e，导出文件可回 draw.io 编辑）")
    border: int = Field(20, ge=0, le=100, description="页边距像素（白色留白），默认 20")


def _run_drawio_export(
    in_path: str, out_path: str, fmt_val: str, *, scale: int | None, width: int | None, embed: bool,
    border: int = 20,
) -> None:
    """调 drawio CLI 导出。非零退出抛 RuntimeError。

    命令构造遵循 drawio-skill troubleshooting 的 Linux 规则：
    --no-sandbox 必须在末尾。HOME 已在 Dockerfile 设为 /tmp。
    """
    cmd = [DRAWIO_BIN, "-x", "-f", fmt_val, "-o", out_path]
    if embed:
        cmd.append("-e")
    if fmt_val in ("png", "jpg"):
        if width is not None:
            cmd += ["--width", str(width)]
        elif scale is not None:
            cmd += ["-s", str(scale)]
        else:
            cmd += ["-s", "3"]  # 默认 3 倍≈300DPI，专利附图高分辨率
    if border > 0:
        cmd += ["-b", str(border)]  # 页边距，必须在 --no-sandbox 之前
    # Chromium 在 docker 内 /dev/shm 默认仅 64MB，易致渲染崩溃，必须禁用 shm
    cmd += ["--disable-gpu", "--disable-dev-shm-usage"]
    cmd.append(in_path)
    cmd.append("--no-sandbox")  # 必须在输入文件之后（末尾）

    logger.info("drawio cmd: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"drawio 退出码 {proc.returncode}: {stderr}")


def _do_render(req: "RenderRequest") -> tuple[bytes, str]:
    """写临时文件、调 CLI、读回字节。返回 (bytes, media_type)。"""
    if req.format not in _FORMATS:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {req.format}")

    fmt_val, media_type = _FORMATS[req.format]
    with tempfile.TemporaryDirectory() as td:
        in_path = str(Path(td) / "input.drawio")
        ext = req.format
        out_path = str(Path(td) / f"output.{ext}")
        Path(in_path).write_text(req.xml, encoding="utf-8")

        try:
            _run_drawio_export(
                in_path, out_path, fmt_val,
                scale=req.scale, width=req.width, embed=req.embed, border=req.border,
            )
        except subprocess.TimeoutExpired as e:
            raise HTTPException(status_code=504, detail="drawio 渲染超时") from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        if not Path(out_path).exists():
            raise HTTPException(status_code=500, detail="drawio 未生成输出文件")
        return Path(out_path).read_bytes(), media_type


@app.get("/health")
def health():
    """健康检查：drawio 二进制存在即可（Chromium 由 xvfb-run 在请求时拉起）。"""
    binary = shutil.which("drawio")
    return {"status": "ok" if binary else "unavailable", "drawio": binary or "not found"}


@app.post("/render")
def render(req: RenderRequest):
    """渲染 drawio XML 为图片，返回二进制字节流。"""
    content, media_type = _do_render(req)
    return Response(content=content, media_type=media_type)
