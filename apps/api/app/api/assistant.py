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
from app.services import conversation_service

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
    from app.ai.brief_dimensions import compute_coverage
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).all()
    # coverage 从 draft_outline 算（零成本，让切会话能恢复 ready 判断）
    coverage = compute_coverage(conv.draft_outline).to_dict()
    return {
        **_conv_to_dict(conv),
        "project_id": str(conv.project_id) if conv.project_id else None,
        "draft_outline": conv.draft_outline,
        "coverage": coverage,
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
import time  # noqa: E402

from fastapi import Body  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from app.ai.init_orchestrator import astream_init_chat, astream_init_generate  # noqa: E402
from app.services import llm_config_service  # noqa: E402

HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_provider(llm_config) -> str:
    """从已解析配置取 provider（用于日志）。无配置返回 'none'。"""
    if llm_config is None:
        return "none"
    return llm_config.source


def _resolve_model(llm_config) -> str:
    """从已解析配置取 model（用于日志）。无配置返回空串。"""
    if llm_config is None:
        return ""
    return llm_config.model or ""


def _log_llm_call(db: Session, *, user_id, action: str, model: str, provider: str,
                  status: str, tokens=None, duration_ms=None, error=None,
                  context_meta=None) -> None:
    """写一条 LLM 调用元数据日志（init 助手版，project_id 恒 None——未落地）。

    与 ai.py._log_llm_call 同构，仅 action 命名不同（init_chat / init_generate）。
    只存元数据不存内容（设计 8.3 红线）。工具是事务边界，失败必 rollback。
    """
    from app.models import LLMCallLog
    try:
        log = LLMCallLog(
            user_id=user_id, project_id=None, action=action,
            model=model, provider=provider, status=status,
            token_prompt=tokens.get("prompt") if tokens else None,
            token_completion=tokens.get("completion") if tokens else None,
            duration_ms=duration_ms, error=error, context_meta=context_meta,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()


class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None


async def _yield_with_heartbeat_tuple(async_gen):
    """(kind, payload) 元组生成器的心跳包装（照搬 ai.py 模式）。

    用 asyncio.wait + task 复用（不用 wait_for，避免超时取消杀掉慢速 LLM 流）。
    原样透传 ("token"|"tool_call"|"tool_result", payload)，超时插 ("heartbeat", None)。
    """
    ait = async_gen.__aiter__()
    nxt = asyncio.ensure_future(ait.__anext__())
    while True:
        done, _pending = await asyncio.wait({nxt}, timeout=HEARTBEAT_INTERVAL)
        if nxt in done:
            try:
                item = nxt.result()
            except StopAsyncIteration:
                break
            yield item
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            yield ("heartbeat", None)


@router.post("/conversations/{conv_id}/chat")
async def chat(
    conv_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """init 助手对话（SSE）。消息存到顶层会话（section_id=NULL）。

    流式 token / tool_call / tool_result；done 事件带 message_id + conversation_id +
    ready_to_create（bool）+ coverage（维度覆盖率）。
    ready_to_create 由维度覆盖率算（brief_dimensions.compute_coverage），不再扫描标记字符串。
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
        # resolve_chat_config 在当前事务做了多次 SELECT，显式 rollback 确保干净事务开始
        db.rollback()
        full_response = ""
        usage = {}  # 降级路径（裸 LLM）填充；agent loop 路径留空
        meta = {}   # 压缩 snapshot 写入，供 _log_llm_call 记 context_meta
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, action="init_chat",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, data in _yield_with_heartbeat_tuple(
                astream_init_chat(
                    db, current_user.id, history, payload.message,
                    llm_config=llm_config, usage_sink=usage, meta_sink=meta,
                )
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                elif kind == "token":
                    full_response += data
                    yield _sse_event("token", {"text": data})
                elif kind == "tool_call":
                    yield _sse_event("tool_call", {"name": data.get("name", ""), "args": data.get("args", {})})
                elif kind == "tool_result":
                    yield _sse_event("tool_result", {"name": data.get("name", ""), "result": data.get("result", "")})
            # 落助手消息
            ai_msg = Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            # 首轮对话：用 LLM 总结生成简短标题（走轻量模型，降级用户消息前缀）。
            # 仅在无历史消息时生成，避免每轮覆盖标题。new_title 通过 done 事件回传前端。
            new_title = None
            if not history:
                new_title = conversation_service.summarize_conversation_title(
                    db, conv, payload.message, full_response, user_id=current_user.id
                )
                conv.title = new_title
            # 提取 8 章草稿大纲（轻量 LLM，失败返回空 dict，不影响主流程）。
            # 基于含本次回复的全量历史重算，幂等。写 draft_outline 供右侧预览实时刷新。
            from app.services.outline_extractor import extract_outline
            full_history = history + [user_msg, ai_msg]
            outline = extract_outline(db, full_history, user_id=current_user.id)
            if outline:
                conv.draft_outline = outline
            # 提交标题/大纲改动（首轮改了 title、或本轮提取到大纲都要落库；
            # 无条件 commit 确保 new_title 即使在大纲为空时也不丢）
            db.commit()
            # 维度覆盖率计算（替代旧的标记字符串扫描）。
            # ready 由核心 5 维覆盖 + 缺点/问题/效果对齐达标决定（brief_dimensions.compute_coverage）。
            from app.ai.brief_dimensions import compute_coverage
            coverage = compute_coverage(outline).to_dict()
            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": str(conv.id),
                "ready_to_create": coverage.get("ready", False),
                "title": new_title,
                "outline": outline,
                "coverage": coverage,
            })
        except asyncio.CancelledError:
            if full_response:
                db.add(Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response))
                db.commit()
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            err = str(e)
            status = "failed"
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})
        finally:
            _log_llm_call(
                db, user_id=current_user.id, action="init_chat",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status=status, tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err, context_meta=meta.get("context_meta"),
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


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


