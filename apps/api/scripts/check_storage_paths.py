"""校验旧 storage_path 数据(迁移 minio 后的排障脚本)。

用法:uv run python -m scripts.check_storage_paths

扫描 attachments / parse_jobs 的 storage_path 字段,识别仍是「本地路径格式」
(含 / 或 \\ 且非 minio key 形如 attachments/.../personal/...)的记录。
这类记录在迁 minio 后会读不到文件,需手动迁移文件到 minio 并改 key。

开发阶段 uploads/ 为空,正常应返回 0 条;生产部署前务必跑一次。
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Attachment, ParseJob


def _looks_like_local_path(path: str) -> bool:
    """minio key 形如 attachments/{uid}/{uuid}.png 或 templates/{uid}/{uuid}.docx
    或 global/.../personal/.../。
    本地路径特征:含盘符(windows)或以 / 开头的绝对路径,或含 uploads/。
    """
    if not path:
        return False
    # windows 盘符 / unix 绝对路径 / 旧 uploads 目录
    return (
        (len(path) > 1 and path[1] == ":")  # C:\...
        or path.startswith("\\")
        or path.startswith("/uploads")
        or path.startswith("uploads/")
        or "\\uploads\\" in path
    )


def main() -> None:
    db = SessionLocal()
    try:
        bad_att = []
        for a in db.scalars(select(Attachment)):
            if _looks_like_local_path(a.storage_path):
                bad_att.append((str(a.id), a.storage_path))

        bad_jobs = []
        for j in db.scalars(select(ParseJob)):
            if _looks_like_local_path(j.source_path):
                bad_jobs.append((str(j.id), j.source_path))

        print(f"附件(storage_path 仍是本地路径):{len(bad_att)} 条")
        for aid, p in bad_att[:10]:
            print(f"  {aid}: {p}")
        print(f"解析任务(source_path 仍是本地路径):{len(bad_jobs)} 条")
        for jid, p in bad_jobs[:10]:
            print(f"  {jid}: {p}")

        total = len(bad_att) + len(bad_jobs)
        if total:
            print(f"\n⚠️  发现 {total} 条记录仍是本地路径格式,需手动迁移文件到 minio。")
        else:
            print("\n✓ 所有 storage_path 均为 minio key 格式,无需迁移。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
