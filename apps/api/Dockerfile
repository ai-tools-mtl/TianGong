# 天工 API 镜像
# 多阶段构建:builder 装依赖,runner 只拷产物,镜像更小更干净
# 参考:https://docs.astral.sh/uv/guides/integration/docker/

FROM python:3.12-slim AS builder

# 装 uv(从官方 distroless 镜像拷二进制)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# bytecode 编译 + 拷贝(非硬链接),让产物能跨阶段拷出
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# 先拷锁文件 + manifest,利用层缓存(代码改动不触发重装依赖)
COPY pyproject.toml uv.lock ./

# 只装运行依赖(不含 dev extras),--frozen 严格按锁
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- 运行阶段 ---
FROM python:3.12-slim AS runner

WORKDIR /app

# 拷虚拟环境(含全部运行依赖)
COPY --from=builder /app/.venv /app/.venv

# 拷应用代码
COPY . .

# venv 进 PATH,直接用 python/uvicorn(不再经 uv run,省一层)
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# 生产配置:去掉 --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
