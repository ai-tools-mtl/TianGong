"""项目初始化助手路由（/projects/{id}/init-*）。

对话式新建项目（详见 docs/superpowers/plans/2026-07-30-init-assistant.md）：
- init-chat：流式对话（SSE），对话挂在项目首个 section 的 conversation 下
- init-generate：批量生成各章节初稿（SSE 进度 + token）
- init-conversation：取已有对话历史（刷新恢复）

与 ai.py 的 section 粒度路由并列，复用 SSE/心跳/日志模式。
"""
import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.init_orchestrator import astream_init_chat, astream_init_generate
from app.core.database import get_db
from app.deps import get_current_user
from app.models import Conversation, Message, Section, User
from app.services import conversation_service, llm_config_service, project_service

router = APIRouter(prefix="/projects", tags=["ai"])

HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_first_section(db: Session, project_id) -> Section:
    """取项目首个 section（按 order，作为对话挂载点）。

    项目创建时已按模板快照生成 8 个空 section，故首个恒存在（order 最小）。
    """
    section = db.scalar(
        select(Section).where(Section.project_id == project_id).order_by(Section.order).limit(1)
    )
    if section is None:
        # 理论不会发生（建项目即生成 section），防御性报错
        from app.core.exceptions import NotFoundError
        raise NotFoundError("项目暂无章节，无法启动初始化对话")
    return section


def _get_init_history(db: Session, section: Section, conversation_id: str | None) -> list[Message]:
    """取初始化对话历史（按 conversation_id 过滤，时间排序）。"""
    query = select(Message).where(Message.section_id == section.id)
    if conversation_id:
        import uuid as _uuid
        try:
            query = query.where(Message.conversation_id == _uuid.UUID(str(conversation_id)))
        except (ValueError, AttributeError):
            pass
    return list(db.scalars(query.order_by(Message.created_at)))


def _get_or_create_init_conversation(
    db: Session, section: Section, conversation_id: str | None
) -> Conversation:
    """获取或创建初始化对话（挂首个 section）。"""
    if conversation_id:
        import uuid as _uuid
        try:
            conv_uuid = _uuid.UUID(str(conversation_id))
            conv = db.scalar(select(Conversation).where(
                (Conversation.id == conv_uuid) & (Conversation.section_id == section.id)
            ))
            if conv:
                return conv
        except (ValueError, AttributeError):
            pass
    conv = Conversation(section_id=section.id, title="项目初始化对话")
    db.add(conv)
    db.flush()
    return conv


class InitChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    chat_source: str | None = None


class InitGenerateRequest(BaseModel):
    conversation_id: str | None = None
    sections: list[str] | None = None  # 按 key 过滤，默认全部
    chat_source: str | None = None


@router.post("/{project_id}/init-chat")
async def init_chat(
    project_id: str,
    payload: InitChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """项目初始化对话（SSE 流式）。

    对话挂在项目首个 section 的 conversation 下（复用 Conversation/Message）。
    流式返回助手 token；done 事件带 conversation_id（首轮新建后回传给前端）。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    section = _get_first_section(db, project.id)
    history = _get_init_history(db, section, payload.conversation_id)
    conv = _get_or_create_init_conversation(db, section, payload.conversation_id)

    # 落用户消息
    user_msg = Message(section_id=section.id, conversation_id=conv.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    # 在 StreamingResponse 构造前解析配置（与 ai.py 一致：ForbiddenError 能正确转 403）
    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=payload.chat_source
    )

    async def generate():
        full_response = ""
        usage = {}
        start = time.monotonic()
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for token in _heartbeat_wrap(astream_init_chat(
                history, payload.message, llm_config=llm_config, usage_sink=usage
            )):
                if token == "__heartbeat__":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += token
                    yield _sse_event("token", {"text": token})
            # 落助手消息
            ai_msg = Message(section_id=section.id, conversation_id=conv.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": str(conv.id),
            })
        except asyncio.CancelledError:
            if full_response:
                db.add(Message(section_id=section.id, conversation_id=conv.id, role="assistant", content=full_response))
                db.commit()
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{project_id}/init-generate")
async def init_generate(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: InitGenerateRequest | None = Body(default=None),
):
    """批量生成项目各章节初稿（SSE 进度 + token）。

    body 可选：sections 按 key 过滤（默认全部 8 章），chat_source 解析配置。
    流式事件：chapter_start / token / chapter_done / all_done。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    section = _get_first_section(db, project.id)
    conversation_id = payload.conversation_id if payload else None
    sections_filter = payload.sections if payload else None
    chat_source = payload.chat_source if payload else None

    history = _get_init_history(db, section, conversation_id)

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=chat_source
    )

    async def generate():
        usage = {}
        start = time.monotonic()
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for kind, data in astream_init_generate(
                db, project, history,
                llm_config=llm_config, sections=sections_filter, usage_sink=usage,
            ):
                if kind == "chapter_start":
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

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/{project_id}/init-conversation")
def get_init_conversation(
    project_id: str,
    conversation_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取初始化对话历史（刷新恢复）。返回 messages + conversation_id。

    无 conversation_id 时取首个 section 下最近的初始化对话。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    section = _get_first_section(db, project.id)

    conv = None
    if conversation_id:
        import uuid as _uuid
        try:
            conv = db.scalar(select(Conversation).where(
                (Conversation.id == _uuid.UUID(conversation_id)) & (Conversation.section_id == section.id)
            ))
        except (ValueError, AttributeError):
            pass
    if conv is None:
        # 取该 section 下最近一个对话（若无则返回空）
        conv = db.scalar(
            select(Conversation).where(Conversation.section_id == section.id)
            .order_by(Conversation.updated_at.desc()).limit(1)
        )

    if conv is None:
        return {"conversation_id": None, "messages": []}

    messages = list(db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ))
    return {
        "conversation_id": str(conv.id),
        "messages": [
            {"id": str(m.id), "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()}
            for m in messages
        ],
    }


async def _heartbeat_wrap(async_gen) -> AsyncIterator[str]:
    """包装 token 生成器，空闲超阈值插 '__heartbeat__' 哨兵（init-chat 用）。

    复用 ai.py 的 asyncio.wait + task 复用策略（不用 wait_for，避免超时取消杀流）。
    """
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
