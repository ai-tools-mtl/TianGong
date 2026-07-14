from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Section, SectionVersion


def list_versions(db: Session, *, section: Section) -> list[SectionVersion]:
    return list(db.scalars(
        select(SectionVersion)
        .where(SectionVersion.section_id == section.id)
        .order_by(SectionVersion.created_at.desc())
    ))


def create_version(
    db: Session, *, section: Section, created_by: str = "manual", note: str | None = None
) -> SectionVersion:
    version = SectionVersion(
        section_id=section.id,
        content=section.content,
        summary=section.summary,
        created_by=created_by,
        note=note,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def rollback_to_version(db: Session, *, section: Section, version_id: str) -> Section:
    try:
        vid = UUID(version_id)
    except ValueError:
        raise NotFoundError("版本不存在")
    version = db.scalar(
        select(SectionVersion).where(
            (SectionVersion.id == vid) & (SectionVersion.section_id == section.id)
        )
    )
    if version is None:
        raise NotFoundError("版本不存在")
    # 回滚前先存当前内容（防丢失）
    if section.content != version.content:
        create_version(db, section=section, created_by="auto", note="回滚前自动保存")
    section.content = version.content
    section.summary = version.summary
    db.commit()
    db.refresh(section)
    return section
