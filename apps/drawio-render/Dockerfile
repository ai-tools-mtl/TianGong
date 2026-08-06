# 天工 drawio 渲染微服务镜像
#
# 跑 draw.io desktop（Electron + Chromium）的 headless CLI 导出。
# 照 apps/nli 的 uv 多阶段范式；差异：runner 阶段额外装 xvfb + Electron GUI 库 + drawio-desktop .deb。
# 镜像较重（Chromium ~300-500MB），start_period 给足；无模型权重，.deb 烤进镜像（离线/内网友好）。

# ---------- builder：装 Python 依赖 ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# bytecode 编译 + 拷贝（跨阶段拷贝需 copy 而非硬链接）
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# 先拷 manifest 利用层缓存
COPY pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

# ---------- runner：系统依赖 + drawio-desktop + 应用 ----------
FROM python:3.12-slim AS runner

WORKDIR /app

# 系统依赖（参考 rlespinasse/docker-drawio-desktop-headless 验证过的清单）：
# - xvfb + xauth：headless 跑 Electron 必需的虚拟 X server
# - dbus + dbus-x11：Chromium/Electron 异步操作依赖，缺失会导致「Export failed」
# - libgtk-3-0 / libnss3 / libgbm1 / libasound2 等：Chromium/Electron 运行库
# - libnotify4 / libxtst6 / libsecret-1-0：draw.io desktop .deb 的运行依赖
# - fonts-noto-cjk：中文等 CJK 标签渲染（专利附图含中文）
# - wget/ca-certificates：下载 .deb
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        xauth \
        x11-utils \
        dbus \
        dbus-x11 \
        libgtk-3-0 \
        libnss3 \
        libasound2 \
        libgbm1 \
        libxkbcommon0 \
        libxshmfence1 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libxtst6 \
        libnotify4 \
        libsecret-1-0 \
        fonts-noto-cjk \
        wget \
        ca-certificates \
    && wget -q "https://github.com/jgraph/drawio-desktop/releases/download/v31.1.5/drawio-amd64-31.1.5.deb" -O /tmp/drawio.deb \
    && (dpkg -i /tmp/drawio.deb || apt-get -f install -y) \
    && rm -f /tmp/drawio.deb \
    && rm -rf /var/lib/apt/lists/*

# 拷虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 拷应用代码（单文件）
COPY main.py entrypoint.sh ./

# venv 进 PATH；HOME 必须可写（drawio-desktop#127：Home directory not accessible）
# ELECTRON_DISABLE_SECURITY_WARNINGS / DRAWIO_DISABLE_UPDATE：抑制 Electron 启动噪声与
# 自动更新检查（headless 无意义且可能拖慢），照 rlespinasse 经验。
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    ELECTRON_DISABLE_SECURITY_WARNINGS="true" \
    DRAWIO_DISABLE_UPDATE="true"

EXPOSE 8001

# entrypoint 起常驻 Xvfb（固定 DISPLAY=:42）再 exec uvicorn（见 entrypoint.sh 注释）。
# Windows checkout 的 CRLF 需修复 + 加可执行权限。
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
