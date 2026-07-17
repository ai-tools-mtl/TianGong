"""AI 流式 SSE 路由（异步 + 心跳 + 服务端真中断 + 断线内容保留）。"""

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import astream_llm
from app.ai.orchestrator import astream_chat, astream_generate, astream_rewrite
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.deps import get_current_user
from app.models import LLMCallLog, Message, Section, User
from app.schemas.ai import ChatRequest, GenerateRequest, RewriteRequest
from app.services import llm_config_service, section_service

router = APIRouter(tags=["ai"])

# 心跳间隔（秒）：空闲超过此值发 heartbeat 事件，防中间代理掐断
HEARTBEAT_INTERVAL = 5.0


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


def _resolve_provider(llm_config) -> str:
    """从已解析配置取 provider（用于日志 provider 字段）。无配置返回 'none'。

    复用上游已 resolve 的 config（I1：避免日志侧二次/三次 resolve 浪费 DB 查询）；
    无配置时返回 'none' 而非 'global'（I2：如实标注失败路径）。
    """
    if llm_config is None:
        return "none"
    return llm_config.source  # "user" / "global" / "env"


def _resolve_model(llm_config) -> str:
    """从已解析配置取 model（用于日志 model 字段）。无配置返回空串。

    复用上游已 resolve 的 config（I1），无配置时返回空串（I2）。
    """
    if llm_config is None:
        return ""
    return llm_config.model or ""


def _log_llm_call(
    db: Session, *,
    user_id, project_id, action: str, model: str, provider: str,
    status: str, tokens=None, duration_ms=None, error=None,
) -> None:
    """写一条 LLM 调用元数据日志（设计 8.3 红线：只存元数据，不存内容）。

    tokens（断链 C3）：可选 dict {"prompt": int, "completion": int}，
    由各端点从流的 usage_metadata（astream_llm 的 usage_sink）捕获；
    无值时落 None（如未开 stream_usage 或 provider 未回传 usage 的情形）。
    """
    try:
        log = LLMCallLog(
            user_id=user_id,
            project_id=project_id,
            action=action,
            model=model,
            provider=provider,
            token_prompt=tokens.get("prompt") if tokens else None,
            token_completion=tokens.get("completion") if tokens else None,
            duration_ms=duration_ms,
            status=status,
            error=(str(error)[:500] if error else None),
        )
        db.add(log)
        db.commit()
    except Exception:
        # 日志失败不阻断主流程（已 yield 给用户的内容不丢）
        db.rollback()


async def _yield_with_heartbeat(async_gen) -> AsyncIterator[tuple[str, str]]:
    """包装异步 token 生成器，空闲超 HEARTBEAT_INTERVAL 时插心跳事件。

    用 asyncio.wait + task 复用（而非 wait_for），避免超时时取消
    __anext__() 导致生成器被永久关闭（wait_for 的 bug 会杀掉慢速 LLM 流）。

    LLM 生成慢或长时间无 token 时，中间代理可能掐断空闲连接；
    心跳让连接保持活跃。token 与心跳交替 yield（统一 str）。
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
            yield ("token", token)
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            # 超时但 task 仍在运行（不取消），发心跳保活
            yield ("heartbeat", "")


@router.post("/sections/{section_id}/chat")
async def chat(
    section_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id)
    user_msg = Message(section_id=section.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    async def generate():
        full_response = ""
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        # 阶段 0：解析生效 LLM 配置（按 source：global/byok/env；None 走 fallback）
        llm_config = llm_config_service.resolve_llm_config(db, user_id=current_user.id, source=payload.source)
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="chat",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_chat(db, section, history, payload.message,
                             llm_config=llm_config, usage_sink=usage)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += text
                    yield _sse_event("token", {"text": text})
            ai_msg = Message(section_id=section.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {"message_id": str(ai_msg.id)})
        except asyncio.CancelledError:
            # 客户端断开：已生成的部分存为 assistant message（断线保留）
            if full_response:
                db.add(Message(section_id=section.id, role="assistant", content=full_response))
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="chat",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/generate")
async def generate_draft(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: GenerateRequest | None = Body(default=None),
):
    # body 可选：前端传 {source} 时解析；无 body（旧调用方）默认 source=None。
    source = payload.source if payload else None
    section, history = _get_section_with_history(db, current_user.id, section_id)

    async def generate():
        full_md = ""
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        llm_config = llm_config_service.resolve_llm_config(db, user_id=current_user.id, source=source)
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="generate",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_generate(db, section, history, llm_config=llm_config, usage_sink=usage)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_md += text
                    yield _sse_event("token", {"text": text})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except asyncio.CancelledError:
            # 客户端断开：仅当 section 当前为空时落半截草稿（避免覆盖已有内容）
            if full_md and section.status == "empty":
                from app.ai.markdown_to_tiptap import markdown_to_tiptap
                section.content = markdown_to_tiptap(full_md)
                section.status = "drafting"
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="generate",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/rewrite")
async def rewrite(
    section_id: str,
    payload: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    async def generate():
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        llm_config = llm_config_service.resolve_llm_config(db, user_id=current_user.id, source=payload.source)
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="rewrite",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_rewrite(section, payload.selected_text, payload.instruction,
                                llm_config=llm_config, usage_sink=usage)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    yield _sse_event("token", {"text": text})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="rewrite",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

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


class CaptionRequest(BaseModel):
    descriptions: list[str]
    source: str | None = None


@router.post("/sections/{section_id}/caption-figures")
async def caption_figures(
    section_id: str,
    payload: CaptionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """图注润色：基于文字描述生成规范图注（设计 9.5，仅文本非多模态）。

    直接用 astream_llm 流式生成（不走 heartbeat 包装，简化文本生成）。
    与其它 LLM 端点一致：成功/失败均写 LLMCallLog（含 token 用量，断链 C3）。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    # 仅附图章节可用
    if section.key != "drawings":
        raise ValidationError("图注润色仅限附图说明章节")

    from langchain_core.messages import HumanMessage, SystemMessage

    descs = "\n".join(f"- {d}" for d in payload.descriptions)
    system = (
        "你是专利交底书撰写助手。请根据用户提供的图片文字描述，"
        "润色生成规范的图注。要求：统一'图 N 是…'格式，简洁准确。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"以下是各图的文字描述，请生成规范图注：\n{descs}"),
    ]

    llm_config = llm_config_service.resolve_llm_config(db, user_id=current_user.id, source=payload.source)

    async def generate():
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="caption",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage):
                yield _sse_event("token", {"text": token})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="caption",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
