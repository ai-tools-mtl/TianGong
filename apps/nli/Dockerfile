# 天工 NLI 微服务镜像
# 轻量单文件 FastAPI，简化 apps/api 的 uv 多阶段范式（无 entrypoint/init_db）。
# 模型权重通过 docker-compose bind mount 注入（不烤进镜像），镜像只含代码+依赖。

FROM python:3.12-slim AS builder

# 装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# bytecode 编译 + 拷贝（跨阶段拷贝需 copy 而非硬链接）
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# 先拷 manifest 利用层缓存
COPY pyproject.toml ./

# 装运行依赖（torch CPU 索引已在 pyproject [tool.uv] 声明）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

# --- 运行阶段 ---
FROM python:3.12-slim AS runner

WORKDIR /app

# 拷虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 拷应用代码（单文件）
COPY main.py ./

# venv 进 PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 7999

# 直接跑 uvicorn（无 entrypoint）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7999"]
