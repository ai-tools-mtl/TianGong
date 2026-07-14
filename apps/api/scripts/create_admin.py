"""命令行创建首个管理员。

用法：
    cd apps/api
    uv run python -m scripts.create_admin --email admin@tiangong.com --password YourPass
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


def create_admin(db: Session, *, email: str, password: str) -> User:
    """创建管理员。幂等：若邮箱已存在则跳过。"""
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        print(f"管理员 {email} 已存在，跳过。")
        return existing
    admin = User(
        email=email,
        password_hash=hash_password(password),
        name="管理员",
        role="admin",
        is_superuser=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"管理员创建成功：{email} (id={admin.id})")
    return admin


def main():
    parser = argparse.ArgumentParser(description="创建首个管理员")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        create_admin(db, email=args.email, password=args.password)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
