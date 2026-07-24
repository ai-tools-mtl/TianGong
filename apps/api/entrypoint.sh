#!/bin/sh
# API 容器入口：初始化数据库 → 启动 uvicorn
#
# 初始化（幂等，由 init_db.py 保证）：
#   - alembic upgrade head（已在 head 则跳过）
#   - 建 admin（由 INIT_ADMIN_* 环境变量传入，已存在则跳过）
#   - seed 默认模板 + Rubric（已存在则跳过）
#
# 这样 docker compose up 即是一键可用系统：容器起来后表/管理员/模板都就位。

set -e

echo "[entrypoint] 等待数据库就绪..."
# 简单轮询：pg 容器虽配了 healthcheck，但 api 启动时可能仍在初始化。
# init_db 内部也做 _check_db_ready，这里多一层等待更稳。
for i in $(seq 1 30); do
  if python -c "from app.core.database import engine; from sqlalchemy import text; engine.connect().execute(text('SELECT 1'))" 2>/dev/null; then
    echo "[entrypoint] 数据库已就绪"
    break
  fi
  echo "[entrypoint] 数据库未就绪，重试 ($i/30)..."
  sleep 2
done

echo "[entrypoint] 执行数据库初始化（迁移 + admin + seed，全部幂等）..."
python -m scripts.init_db

echo "[entrypoint] 启动 uvicorn..."
# exec 让 uvicorn 接管 PID 1，正确接收 SIGTERM 等信号（优雅停机）
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
