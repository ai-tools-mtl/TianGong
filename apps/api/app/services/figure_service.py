"""专利附图 AI 生成服务。

流程：校验章节归属 → resolve chat 配置 → LLM 生成 drawio XML → drawio 渲染容器出 PNG →
存 MinIO + 建 Attachment + 建 Figure 记录。

照 summary_service（同步 get_llm().invoke()）+ attachment_service（storage.put + Attachment）
+ nli 模式（调外部微服务）。设计决策见 docs 与 figure_prompts.py 顶部说明。

关键约束：渲染失败（ServiceUnavailableError）时**不落库**——figure 生成是原子操作，
渲染失败就没有可交付的图，让用户重试，不留半成品 Figure 记录。
"""
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import Storage
from app.models import Attachment, Figure, Section
from app.services import drawio_client, llm_config_service, section_service
from app.services.attachment_service import _detect_mime, _ext_for_mime
from app.services.llm_log_helper import log_chat_call

# 一次 figure 生成最多渲染的 PNG 大小（防 LLM 产出异常巨大图撑爆存储）
_MAX_PNG_BYTES = 10 * 1024 * 1024  # 10MB（与 max_image_size_mb 量级一致）


def _to_figure_out(fig: Figure, *, project_id: str) -> dict:
    """Figure ORM → 响应 dict（不含 drawio_xml，详情接口另给）。"""
    return {
        "id": str(fig.id),
        "project_id": str(fig.project_id),
        "section_id": str(fig.section_id) if fig.section_id else None,
        "attachment_id": str(fig.attachment_id) if fig.attachment_id else None,
        "prompt": fig.prompt,
        "diagram_type": fig.diagram_type,
        "created_at": fig.created_at.isoformat(),
        "updated_at": fig.updated_at.isoformat(),
    }


def _to_figure_detail(fig: Figure) -> dict:
    """Figure 详情（含 drawio_xml 源，供前端重新编辑/导出回 draw.io）。"""
    out = _to_figure_out(fig, project_id=str(fig.project_id))
    out["drawio_xml"] = fig.drawio_xml
    return out


def _store_png(
    db: Session, *, storage: Storage, user_id, project_id: str, section_id: str | None,
    png: bytes, name: str,
) -> Attachment:
    """校验 + 存 MinIO + 建 Attachment 记录（复用 attachment_service 的魔数校验逻辑）。"""
    real_mime = _detect_mime(png)
    if real_mime != "image/png":
        raise ValidationError("渲染产物不是有效 PNG")

    if len(png) > _MAX_PNG_BYTES:
        raise ValidationError("生成的附图过大，请简化图结构后重试")

    object_key = f"attachments/{user_id}/{uuid.uuid4()}{_ext_for_mime(real_mime)}"
    storage.put("personal", object_key, png, real_mime)
    att = Attachment(
        project_id=uuid.UUID(project_id),
        section_id=uuid.UUID(section_id) if section_id else None,
        filename=name,
        storage_path=object_key,
        mime_type=real_mime,
        size=len(png),
    )
    db.add(att)
    db.flush()  # 拿到 att.id 供 Figure 引用
    return att


def generate_figure(
    db: Session, *, storage: Storage, user_id, section_id: str,
    prompt: str, diagram_type: str | None, chat_source: str | None,
) -> Figure:
    """生成一张专利附图（LLM 出 XML → 渲染 PNG → 落库）。"""
    from langchain_core.messages import HumanMessage

    from app.ai.figure_prompts import build_figure_prompt, extract_xml
    from app.ai.llm_client import get_llm

    # 1. 校验章节归属（复用 section_service 的资源级授权）
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    if section.key != "drawings":
        raise ValidationError("附图生成仅限「附图说明」章节")

    # 2. 解析 chat 配置（无配置抛 403，由全局异常处理器转响应）
    llm_config = llm_config_service.resolve_chat_config(db, user_id=user_id, chat_source=chat_source)
    if llm_config is None:
        raise ValidationError("未配置 LLM 源，请先在设置中选择")

    # 3. LLM 生成 drawio XML（同步一次性调用，照 summary_service）
    llm = get_llm(llm_config)
    user_msg = build_figure_prompt(prompt, diagram_type)
    start = time.monotonic()
    log_status, log_err = "success", None
    try:
        resp = llm.invoke([HumanMessage(content=user_msg)])
    except Exception as e:
        log_status, log_err = "failed", e
        log_chat_call(
            db, user_id=user_id, project_id=section.project_id, action="figure",
            model=llm_config.model or "", provider=llm_config.source,
            status="failed", duration_ms=int((time.monotonic() - start) * 1000), error=e,
        )
        raise
    log_chat_call(
        db, user_id=user_id, project_id=section.project_id, action="figure",
        model=llm_config.model or "", provider=llm_config.source,
        status=log_status, duration_ms=int((time.monotonic() - start) * 1000), error=log_err,
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    drawio_xml = extract_xml(raw)

    if "<mxfile" not in drawio_xml:
        raise ValidationError("LLM 未返回有效的 drawio XML，请重试或调整描述")

    # 4. 渲染 PNG（失败抛 ServiceUnavailableError，不落库）
    png = drawio_client.render(drawio_xml, fmt="png", scale=2, embed=True)

    # 5. 存 MinIO + 建 Attachment + 建 Figure（单事务）
    name = f"{(prompt[:20] or '附图')}.drawio.png"
    att = _store_png(
        db, storage=storage, user_id=user_id,
        project_id=str(section.project_id), section_id=section_id,
        png=png, name=name,
    )
    fig = Figure(
        project_id=section.project_id,
        section_id=section.id,
        attachment_id=att.id,
        prompt=prompt,
        drawio_xml=drawio_xml,
        diagram_type=diagram_type,
    )
    db.add(fig)
    db.commit()
    db.refresh(fig)
    return fig


def regenerate_figure(
    db: Session, *, storage: Storage, user_id, figure_id: str,
    prompt: str | None, chat_source: str | None,
) -> Figure:
    """用新/旧 prompt 重新生成某张附图，替换其 PNG（保留 XML 源更新）。"""
    fig = get_figure(db, user_id=user_id, figure_id=figure_id)
    new_prompt = prompt or fig.prompt

    from langchain_core.messages import HumanMessage

    from app.ai.figure_prompts import build_figure_prompt, extract_xml
    from app.ai.llm_client import get_llm

    llm_config = llm_config_service.resolve_chat_config(db, user_id=user_id, chat_source=chat_source)
    if llm_config is None:
        raise ValidationError("未配置 LLM 源，请先在设置中选择")

    llm = get_llm(llm_config)
    start = time.monotonic()
    try:
        resp = llm.invoke([HumanMessage(content=build_figure_prompt(new_prompt, fig.diagram_type))])
    except Exception as e:
        log_chat_call(
            db, user_id=user_id, project_id=fig.project_id, action="figure",
            model=llm_config.model or "", provider=llm_config.source,
            status="failed", duration_ms=int((time.monotonic() - start) * 1000), error=e,
        )
        raise
    log_chat_call(
        db, user_id=user_id, project_id=fig.project_id, action="figure",
        model=llm_config.model or "", provider=llm_config.source,
        status="success", duration_ms=int((time.monotonic() - start) * 1000),
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    drawio_xml = extract_xml(raw)
    if "<mxfile" not in drawio_xml:
        raise ValidationError("LLM 未返回有效的 drawio XML，请重试或调整描述")

    png = drawio_client.render(drawio_xml, fmt="png", scale=2, embed=True)

    # 替换 Attachment：删旧 PNG 对象，存新 PNG。旧 Attachment 记录由 SET NULL 不级联。
    old_attachment_id = fig.attachment_id
    name = f"{(new_prompt[:20] or '附图')}.drawio.png"
    att = _store_png(
        db, storage=storage, user_id=user_id,
        project_id=str(fig.project_id), section_id=str(fig.section_id) if fig.section_id else None,
        png=png, name=name,
    )
    fig.attachment_id = att.id
    fig.prompt = new_prompt
    fig.drawio_xml = drawio_xml

    # 删旧 Attachment（若有）
    if old_attachment_id:
        old_att = db.get(Attachment, old_attachment_id)
        if old_att:
            try:
                storage.delete("personal", old_att.storage_path)  # 幂等
            except Exception:
                pass  # 删存储失败不阻断主流程，对象可能已不存在
            db.delete(old_att)

    db.commit()
    db.refresh(fig)
    return fig


def list_figures(db: Session, *, user_id, project_id: str, section_id: str | None = None) -> list[Figure]:
    """列出项目的附图（先校验项目归属）。"""
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == uuid.UUID(project_id)))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    query = select(Figure).where(Figure.project_id == project.id)
    if section_id:
        query = query.where(Figure.section_id == uuid.UUID(section_id))
    return list(db.scalars(query.order_by(Figure.created_at.desc())))


def get_figure(db: Session, *, user_id, figure_id: str) -> Figure:
    """获取附图（含归属校验）。"""
    try:
        fid = uuid.UUID(figure_id)
    except ValueError:
        raise NotFoundError("附图不存在")
    fig = db.get(Figure, fid)
    if fig is None:
        raise NotFoundError("附图不存在")
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == fig.project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("附图不存在")
    return fig


def delete_figure(db: Session, *, storage: Storage, user_id, figure_id: str) -> None:
    """删除附图（Figure + 关联 Attachment + MinIO 对象，幂等）。"""
    fig = get_figure(db, user_id=user_id, figure_id=figure_id)
    if fig.attachment_id:
        att = db.get(Attachment, fig.attachment_id)
        if att:
            try:
                storage.delete("personal", att.storage_path)
            except Exception:
                pass
            db.delete(att)
    db.delete(fig)
    db.commit()
