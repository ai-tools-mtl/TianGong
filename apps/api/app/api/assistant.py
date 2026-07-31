"""项目初始化助手路由（/assistant/conversations/*）—— ChatGPT 式独立对话页后端。

顶层 init 会话（kind='init'，项目无关）：列表/创建/取历史/删除。
chat/generate 端点见同文件下方。

详见 docs/superpowers/specs/2026-07-31-chatgpt-style-init-assistant-design.md。
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import Conversation, KIND_INIT, Message, User

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _conv_to_dict(c: Conversation) -> dict:
    return {
        "id": str(c.id),
        "title": c.title,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "updated_at": c.updated_at.isoformat() if c.updated_at else "",
    }


def _get_owned_conversation(db: Session, user_id, conv_id: str) -> Conversation:
    """取会话并校验归属（init 会话靠 user_id）。

    非本人、非 init 类型、或不存在均返回 404（防探测：统一 NotFound，不透露存在性）。
    注意：已落地的会话（project_id 非 NULL）仍可读（用于查看历史），但不可删/不可再 generate。
    """
    from app.core.exceptions import NotFoundError
    try:
        cid = uuid.UUID(conv_id)
    except (ValueError, AttributeError):
        raise NotFoundError("会话不存在")
    conv = db.scalar(select(Conversation).where(
        Conversation.id == cid,
        Conversation.user_id == user_id,
        Conversation.kind == KIND_INIT,
    ))
    if conv is None:
        raise NotFoundError("会话不存在")
    return conv


@router.get("/conversations")
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的未落地 init 会话（kind=init AND project_id IS NULL）。"""
    convs = db.scalars(
        select(Conversation).where(
            Conversation.user_id == current_user.id,
            Conversation.kind == KIND_INIT,
            Conversation.project_id.is_(None),
        ).order_by(Conversation.updated_at.desc())
    ).all()
    return [_conv_to_dict(c) for c in convs]


class ConversationCreateIn(BaseModel):
    title: str | None = None


@router.post("/conversations", status_code=201)
def create_conversation(
    payload: ConversationCreateIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建空 init 会话。"""
    conv = Conversation(
        kind=KIND_INIT,
        user_id=current_user.id,
        section_id=None,
        title=(payload.title if payload and payload.title else "新对话"),
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conv_to_dict(conv)


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取会话 + 消息历史。已落地的会话（project_id 非 NULL）也允许读。"""
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).all()
    return {
        **_conv_to_dict(conv),
        "project_id": str(conv.project_id) if conv.project_id else None,
        "messages": [
            {"id": str(m.id), "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in messages
        ],
    }


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除会话（级联消息）。只允许删未落地的（project_id NULL）。"""
    from app.core.exceptions import ValidationError
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    if conv.project_id is not None:
        raise ValidationError("已落地为项目的会话不可删除")
    db.delete(conv)
    db.commit()
    return None
