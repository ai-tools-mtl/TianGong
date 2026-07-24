"""初始化数据库：跑全部 alembic 迁移到 head，可选创建管理员，并 seed 默认模板/Rubric。

这是一个幂等脚本，重复执行不会报错（alembic 已在 head 时跳过，admin
已存在时跳过，默认模板/Rubric 已存在时跳过）。容器由用户自行启动，本
脚本只负责建表、建账号、seed 系统默认数据。

前置条件（脚本会检测，不通会明确提示）：
    docker compose up -d postgres

用法：
    cd apps/api
    # 仅初始化表结构
    uv run python -m scripts.init_db
    # 初始化并同时建 admin（命令行参数）
    uv run python -m scripts.init_db --admin-username admin --admin-password 'admin.123' --admin-email admin@tiangong.dev

管理员账号来源（优先级：命令行参数 > 环境变量 > 跳过）：
    --admin-username / --admin-password / --admin-email
    或环境变量 INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD / INIT_ADMIN_EMAIL
    容器启动时通过 entrypoint.sh 调用本脚本，由 compose 注入环境变量。

注意：
- 本脚本不做 docker 容器启停，也不删数据。若要彻底重置库，请手动执行
  `docker compose down -v` 后重新起容器，再跑本脚本。
- pgvector 扩展依赖已在迁移 ee50036c9e86 内部处理（CREATE EXTENSION IF NOT EXISTS），
  无需手动安装。
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal, engine


def _check_db_ready() -> None:
    """检测数据库连通性；不通时打印明确引导后退出。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — 启动期失败统一兜底
        print(f"✗ 无法连接数据库：{e.__class__.__name__}: {e}")
        print()
        print("请先启动 postgres 容器：")
        print("    docker compose up -d postgres")
        print("并在 apps/api/.env 配置正确的 DATABASE_URL。")
        raise SystemExit(1)
    print("✓ 数据库连通")


def _run_migrations() -> None:
    """编程式调用 alembic upgrade head（不 shell out，跨平台可控）。"""
    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parent.parent  # apps/api
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    # env.py 会用 app.core.config.get_settings() 注入 URL，这里也显式设一份
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
    print("✓ 数据库已迁移到 head")


def _maybe_create_admin(args: argparse.Namespace) -> None:
    """复用 create_admin.create_admin（幂等），未传参数则跳过。"""
    if not (args.admin_username and args.admin_password):
        print("• 未提供 --admin-username/--admin-password，跳过管理员创建")
        return
    from scripts.create_admin import create_admin

    db = SessionLocal()
    try:
        create_admin(
            db,
            username=args.admin_username,
            password=args.admin_password,
            email=args.admin_email,
        )
    finally:
        db.close()


def _seed_system_defaults() -> None:
    """seed 系统默认模板 + 默认 Rubric（幂等）。"""
    from app.services.seed_service import (
        ensure_default_rubric,
        ensure_default_template,
    )

    db = SessionLocal()
    try:
        tpl = ensure_default_template(db)
        rubric = ensure_default_rubric(db)
        print(f"✓ 默认模板就绪：{tpl.name} (id={tpl.id})")
        print(f"✓ 默认 Rubric 就绪：{rubric.name} (id={rubric.id})")
    finally:
        db.close()


def main() -> int:
    import os

    parser = argparse.ArgumentParser(
        description="初始化数据库（迁移到 head，可选建管理员）"
    )
    parser.add_argument(
        "--admin-username",
        default=None,
        help="管理员登录用户名（3-32 位字母数字下划线连字符）",
    )
    parser.add_argument(
        "--admin-password",
        default=None,
        help="管理员密码",
    )
    parser.add_argument(
        "--admin-email",
        default=None,
        help="管理员联系方式邮箱（可选，须用合法域名）",
    )
    args = parser.parse_args()

    # 环境变量兜底：命令行参数未传时，读 INIT_ADMIN_*（容器启动用）。
    # 优先级：命令行参数 > 环境变量 > 跳过。
    if not args.admin_username:
        args.admin_username = os.environ.get("INIT_ADMIN_USERNAME") or None
    if not args.admin_password:
        args.admin_password = os.environ.get("INIT_ADMIN_PASSWORD") or None
    if not args.admin_email:
        args.admin_email = os.environ.get("INIT_ADMIN_EMAIL") or None

    _check_db_ready()
    _run_migrations()
    _maybe_create_admin(args)
    _seed_system_defaults()
    print()
    print("✓ 数据库初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
