"""初始化系统默认模板。"""

from app.core.database import SessionLocal
from app.services.seed_service import ensure_default_template


def main():
    db = SessionLocal()
    try:
        tpl = ensure_default_template(db)
        print(f"默认模板就绪：{tpl.name} (id={tpl.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
