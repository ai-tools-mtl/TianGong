"""AI 流式 SSE 路由。"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import stream_chat, stream_generate, stream_rewrite
from app.core.database import get_db
from app.deps import get_current_user
from app.models import Message, Section, User
from app.schemas.ai import ChatRequest, RewriteRequest
from app.services import section_service

router = APIRouter(tags=["ai"])


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_section_with_history(
    db: Session, user_id, section_id: str
) -> tuple[Section, list[Message]]:
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    history = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return section, history


@router.post("/sections/{section_id}/chat")
def chat(
    section_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id)
    user_msg = Message(section_id=section.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    def generate():
        full_response = ""
        try:
            for token in stream_chat(db, section, history, payload.message):
                full_response += token
                yield _sse_event("token", {"text": token})
            ai_msg = Message(section_id=section.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {"message_id": str(ai_msg.id)})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/generate")
def generate_draft(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id)

    def generate():
        full_md = ""
        try:
            for token in stream_generate(db, section, history):
                full_md += token
                yield _sse_event("token", {"text": token})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/rewrite")
def rewrite(
    section_id: str,
    payload: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    def generate():
        try:
            for token in stream_rewrite(section, payload.selected_text, payload.instruction):
                yield _sse_event("token", {"text": token})
            yield _sse_event("done", {})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sections/{section_id}/messages")
def list_messages(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    messages = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]
