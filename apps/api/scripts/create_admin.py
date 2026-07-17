"""命令行创建首个管理员。

用法：
    cd apps/api
    uv run python -m scripts.create_admin --username admin --password YourPass
    uv run python -m scripts.create_admin --username admin --password YourPass --email admin@example.com
"""

import argparse
import re
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


def create_admin(
    db: Session, *, username: str, password: str, email: str | None = None
) -> User:
    """创建管理员。幂等：若用户名已存在则跳过。

    username 必填（与 RegisterRequest 相同的格式约束）。
    email 可选；提供时走与注册相同的邮箱校验（G4：.local/.localhost 等保留
    域名会被 EmailStr 拒绝），避免"能创建却登不进"的陷阱。
    """
    # username 格式校验（镜像 RegisterRequest 的 field_validator）
    if not _USERNAME_RE.match(username):
        print(
            "错误：用户名不合法 —— 仅允许字母、数字、下划线和连字符，"
            "长度 3-32。"
        )
        raise SystemExit(1)

    # email 校验（仅当提供时）——G4 保护保留
    if email:
        from email_validator import EmailNotValidError, validate_email
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError as e:
            print(f"错误：邮箱 {email} 不合法 —— {e}. 请用合法域名（如 admin@example.com）")
            raise SystemExit(1) from e

    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        print(f"管理员 {username} 已存在，跳过。")
        return existing
    admin = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        name="管理员",
        role="admin",
        is_superuser=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"管理员创建成功：{username} (id={admin.id})")
    return admin


def main():
    parser = argparse.ArgumentParser(description="创建首个管理员")
    parser.add_argument("--username", required=True, help="登录用户名（3-32 位字母数字下划线连字符）")
    parser.add_argument("--password", required=True)
    parser.add_argument("--email", required=False, default=None, help="可选联系方式邮箱")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        create_admin(db, username=args.username, password=args.password, email=args.email)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
