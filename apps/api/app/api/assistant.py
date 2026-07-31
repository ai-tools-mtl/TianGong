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


# ── 对话 + 落地（SSE 流式）──

import asyncio  # noqa: E402

from fastapi import Body  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from app.ai.init_orchestrator import astream_init_chat, astream_init_generate  # noqa: E402
from app.services import llm_config_service  # noqa: E402

HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None


@router.post("/conversations/{conv_id}/chat")
async def chat(
    conv_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """init 助手对话（SSE）。消息存到顶层会话（section_id=NULL）。

    流式 token；done 事件带 message_id + conversation_id + ready_to_create（bool）。
    ready_to_create 由 assistant 回复是否含 [READY_TO_CREATE] 标记判定（前端据此渲染扳机）。
    """
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    history = list(db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ))
    # 落用户消息（init 消息 section_id=NULL）
    user_msg = Message(conversation_id=conv.id, section_id=None, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=payload.chat_source
    )

    async def generate():
        full_response = ""
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for token in _heartbeat_wrap(astream_init_chat(
                history, payload.message, llm_config=llm_config
            )):
                if token == "__heartbeat__":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += token
                    yield _sse_event("token", {"text": token})
            # 落助手消息
            ai_msg = Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            # 判定时机标记
            ready = "[READY_TO_CREATE]" in full_response
            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": str(conv.id),
                "ready_to_create": ready,
            })
        except asyncio.CancelledError:
            if full_response:
                db.add(Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response))
                db.commit()
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _heartbeat_wrap(async_gen):
    """token 生成器心跳包装（复用 ai.py 模式，用 asyncio.wait 避免超时杀流）。"""
    ait = async_gen.__aiter__()
    nxt = asyncio.ensure_future(ait.__anext__())
    while True:
        done, _pending = await asyncio.wait({nxt}, timeout=HEARTBEAT_INTERVAL)
        if nxt in done:
            try:
                token = nxt.result()
            except StopAsyncIteration:
                break
            yield token
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            yield "__heartbeat__"


class GenerateRequest(BaseModel):
    sections: list[str] | None = None  # 按 key 过滤，默认全部
    chat_source: str | None = None


@router.post("/conversations/{conv_id}/generate")
async def generate(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: GenerateRequest | None = Body(default=None),
):
    """扳机落地：为 init 会话建项目 + 填章节初稿（SSE 进度）。

    用户在前端按「创建项目」扳机后调用。流式事件：
    project_created / chapter_start / token / chapter_done / done。
    会话 project_id 被填上（落地标记）→ 列表不再显示。
    """
    from app.core.exceptions import ValidationError
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    # 防重复落地
    if conv.project_id is not None:
        raise ValidationError("该会话已落地为项目")

    history = list(db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ))

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=(payload.chat_source if payload else None)
    )
    sections_filter = payload.sections if payload else None

    async def generate_stream():
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for kind, data in astream_init_generate(
                db, conv, history, current_user,
                llm_config=llm_config, sections=sections_filter,
            ):
                if kind == "project_created":
                    yield _sse_event("project_created", data)
                elif kind == "chapter_start":
                    yield _sse_event("chapter_start", data)
                elif kind == "token":
                    yield _sse_event("token", {"text": data})
                elif kind == "chapter_done":
                    yield _sse_event("chapter_done", data)
                elif kind == "all_done":
                    yield _sse_event("done", data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


