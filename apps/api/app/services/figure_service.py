"""专利附图 AI 生成服务。

流程：校验章节归属 → resolve chat 配置 → LLM 生成 drawio XML → drawio 渲染容器出 PNG →
存 MinIO + 建 Attachment + 建 Figure 记录。

照 summary_service（同步 get_llm().invoke()）+ attachment_service（storage.put + Attachment）
+ nli 模式（调外部微服务）。设计决策见 docs 与 figure_prompts.py 顶部说明。

关键约束：渲染失败（ServiceUnavailableError）时**不落库**——figure 生成是原子操作，
渲染失败就没有可交付的图，让用户重试，不留半成品 Figure 记录。
"""
import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError
from app.core.storage import Storage
from app.models import Attachment, Figure, Section
from app.services import drawio_client, llm_config_service, section_service
from app.services.attachment_service import _detect_mime
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
        "style": fig.style,
        "number": fig.number,
        "created_at": fig.created_at.isoformat(),
        "updated_at": fig.updated_at.isoformat(),
    }


def _to_figure_detail(fig: Figure) -> dict:
    """Figure 详情（含 drawio_xml 源，供前端重新编辑/导出回 draw.io）。"""
    out = _to_figure_out(fig, project_id=str(fig.project_id))
    out["drawio_xml"] = fig.drawio_xml
    return out


def _validate_rendered_png(png: bytes) -> None:
    """校验渲染产物是可入库的 PNG（魔数 + 大小上限）。

    新建与覆写两条落库路径必须同一标准：覆写把字节写进正文正在引用的旧对象，
    异常内容（如渲染服务 200 返回的空文件/错误页）一旦写入，正文原有图即被
    破坏且不可恢复——校验必须放在 put 之前，两处调用不许只留一处。
    """
    if _detect_mime(png) != "image/png":
        raise ValidationError("渲染产物不是有效 PNG")
    if len(png) > _MAX_PNG_BYTES:
        raise ValidationError("生成的附图过大，请简化图结构后重试")


def _store_png(
    db: Session, *, storage: Storage, user_id, project_id: str, section_id: str | None,
    png: bytes, name: str,
) -> Attachment:
    """校验 + 存 MinIO + 建 Attachment 记录（复用 attachment_service 的魔数校验逻辑）。"""
    _validate_rendered_png(png)

    object_key = f"attachments/{user_id}/{uuid.uuid4()}.png"
    storage.put("personal", object_key, png, "image/png")
    att = Attachment(
        project_id=uuid.UUID(project_id),
        section_id=uuid.UUID(section_id) if section_id else None,
        filename=name,
        storage_path=object_key,
        mime_type="image/png",
        size=len(png),
    )
    db.add(att)
    db.flush()  # 拿到 att.id 供 Figure 引用
    return att


def generate_figure(
    db: Session, *, storage: Storage, user_id, section_id: str,
    prompt: str, diagram_type: str | None, chat_source: str | None,
    style: str | None = None,
) -> Figure:
    """生成一张专利附图（LLM 出 XML → 渲染 PNG → 落库）。"""
    from langchain_core.messages import HumanMessage

    from app.ai.figure_prompts import build_figure_prompt, extract_xml
    from app.ai.llm_client import invoke_llm

    # 1. 校验章节归属（复用 section_service 的资源级授权）
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    if section.key != "drawings":
        raise ValidationError("附图生成仅限「附图」章节")

    # 2. 解析 chat 配置（无配置抛 403，由全局异常处理器转响应）
    llm_config = llm_config_service.resolve_chat_config(db, user_id=user_id, chat_source=chat_source)
    if llm_config is None:
        raise ValidationError("未配置 LLM 源，请先在设置中选择")

    # 3. LLM 生成 drawio XML（同步一次性调用，走 invoke_llm 带 P0-3 timeout + P0-4 重试）
    from app.ai.figure_presets import get_preset
    preset = get_preset(style)
    user_msg = build_figure_prompt(prompt, diagram_type, style=style)
    start = time.monotonic()
    log_status, log_err = "success", None
    try:
        resp = invoke_llm(llm_config, [HumanMessage(content=user_msg)])
    except Exception as e:
        log_status, log_err = "failed", e
        log_chat_call(
            db, user_id=user_id, project_id=section.project_id, action="figure",
            model=llm_config.model or "", provider=llm_config.source,
            status="failed", duration_ms=int((time.monotonic() - start) * 1000), error=e,
        )
        # LLM provider 异常（余额不足/Key 失效/网络等）转友好错误，避免裸 500
        from app.ai.llm_errors import friendly_llm_error
        raise ServiceUnavailableError(friendly_llm_error(e)) from e
    log_chat_call(
        db, user_id=user_id, project_id=section.project_id, action="figure",
        model=llm_config.model or "", provider=llm_config.source,
        status=log_status, duration_ms=int((time.monotonic() - start) * 1000), error=log_err,
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    drawio_xml = extract_xml(raw)

    if "<mxfile" not in drawio_xml:
        raise ValidationError("LLM 未返回有效的 drawio XML，请重试或调整描述")

    # 4. 渲染 PNG（失败抛 ServiceUnavailableError，不落库）；scale/border 随预设
    r = preset["render"]
    png = drawio_client.render(drawio_xml, fmt="png", scale=r["scale"], embed=True, border=r["border"])

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
        style=preset["id"],
        number=_next_figure_number(db, section.project_id),
    )
    db.add(fig)
    db.commit()
    db.refresh(fig)
    return fig


def _next_figure_number(db: Session, project_id) -> int:
    """分配项目内下一个图号（max+1）。

    先以 FOR UPDATE 锁定项目全部现有图行，与删除重排事务串行化：删除侧的
    DELETE/重排 UPDATE 行锁未释放时此处阻塞，拿到锁后在 READ COMMITTED 下
    读到重排后的最新状态——避免「按旧快照算 max+1 撞上并发重排留空洞」。
    SQLite 无 FOR UPDATE（方言层静默忽略），测试环境天然串行不受影响；
    残余极端交错撞唯一约束时 IntegrityError 上抛（用户重试即可）。
    """
    numbers = db.scalars(
        select(Figure.number)
        .where(Figure.project_id == project_id)
        .order_by(Figure.number)  # 与 _renumber_figures 同序加锁，杜绝两路径交错互等的死锁窗口
        .with_for_update()
    ).all()
    return (max(numbers) if numbers else 0) + 1


def _renumber_figures(db: Session, project_id) -> None:
    """删除图后重排：按现 number 升序压成 1..n（无空洞，《专利审查指南》顺序编号要求）。

    压缩方向保序——只把被删图之后的图号前移，之前的图号不动，正文「图K」引用的
    变化面最小。两阶段落位（先挪唯一负数槽，再压回 1..n）：uq(project_id, number)
    下逐行直改会有瞬态撞唯一约束的风险（UPDATE 执行顺序不保证），负数槽与正数
    目标全程不相交，任何语句顺序都安全。SELECT 带 FOR UPDATE 与生成侧的图号分配
    串行化（两侧同序加锁，后到者读到先到者提交后的最新编号，见 _next_figure_number）。
    调用方在同一事务内 commit。
    """
    figs = list(db.scalars(
        select(Figure)
        .where(Figure.project_id == project_id)
        .order_by(Figure.number)
        .with_for_update()
    ))
    if not figs:
        return
    for i, fig in enumerate(figs):
        if fig.number != i + 1:
            fig.number = -(i + 1)
    db.flush()
    for i, fig in enumerate(figs):
        if fig.number < 0:
            fig.number = i + 1


def find_body_references(db: Session, *, project_id, attachment_id) -> list[dict]:
    """扫描项目全部章节正文，找出引用了该附件的章节（服务端权威探测）。

    正文图 <img src> 是 attachmentUrl(project_id, attachment_id)——URL 内含
    attachment id，故把章节 content（Tiptap JSON）序列化后做子串匹配即可。
    前端的同类探测读的是 react-query 缓存（可能滞后），这里以落库内容为准。
    返回 [{section_id, section_title}]；无引用返回 []。
    """
    if attachment_id is None:
        return []
    needle = str(attachment_id)
    hits = []
    for s in db.scalars(select(Section).where(Section.project_id == project_id)):
        if s.content and needle in json.dumps(s.content, ensure_ascii=False):
            hits.append({"section_id": str(s.id), "section_title": s.title})
    return hits


def regenerate_figure(
    db: Session, *, storage: Storage, user_id, figure_id: str,
    prompt: str | None, chat_source: str | None, style: str | None = None,
) -> Figure:
    """用新/旧 prompt 重新生成某张附图，原地覆写其 PNG（attachment_id 不变）。"""
    fig = get_figure(db, user_id=user_id, figure_id=figure_id)
    new_prompt = prompt or fig.prompt
    # style 复用：未传则沿用原 figure 的 style（对齐 prompt 的复用模式）
    from app.ai.figure_presets import get_preset
    preset = get_preset(style or fig.style)

    from langchain_core.messages import HumanMessage

    from app.ai.figure_prompts import build_figure_prompt, extract_xml
    from app.ai.llm_client import invoke_llm

    llm_config = llm_config_service.resolve_chat_config(db, user_id=user_id, chat_source=chat_source)
    if llm_config is None:
        raise ValidationError("未配置 LLM 源，请先在设置中选择")

    start = time.monotonic()
    try:
        resp = invoke_llm(llm_config, [HumanMessage(content=build_figure_prompt(new_prompt, fig.diagram_type, style=preset["id"]))])
    except Exception as e:
        log_chat_call(
            db, user_id=user_id, project_id=fig.project_id, action="figure",
            model=llm_config.model or "", provider=llm_config.source,
            status="failed", duration_ms=int((time.monotonic() - start) * 1000), error=e,
        )
        from app.ai.llm_errors import friendly_llm_error
        raise ServiceUnavailableError(friendly_llm_error(e)) from e
    log_chat_call(
        db, user_id=user_id, project_id=fig.project_id, action="figure",
        model=llm_config.model or "", provider=llm_config.source,
        status="success", duration_ms=int((time.monotonic() - start) * 1000),
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    drawio_xml = extract_xml(raw)
    if "<mxfile" not in drawio_xml:
        raise ValidationError("LLM 未返回有效的 drawio XML，请重试或调整描述")

    r = preset["render"]
    png = drawio_client.render(drawio_xml, fmt="png", scale=r["scale"], embed=True, border=r["border"])

    # 原地覆写（2026-08-25 引用完整性）：渲染产物写回旧 Attachment 的同一存储对象，
    # attachment_id 不变——正文里已插入的图（src 含该 id）自动同步为新图，不再出现
    # 「重生成后正文图片失效」。一个 Figure 恒对应一个 Attachment，覆写无孤儿产生。
    name = f"{(new_prompt[:20] or '附图')}.drawio.png"
    att = db.get(Attachment, fig.attachment_id) if fig.attachment_id else None
    if att is None:
        # 历史遗留（Figure 无 Attachment）→ 走新建
        att = _store_png(
            db, storage=storage, user_id=user_id,
            project_id=str(fig.project_id),
            section_id=str(fig.section_id) if fig.section_id else None,
            png=png, name=name,
        )
        fig.attachment_id = att.id
    else:
        # 与 _store_png 同标准：覆写的是正文正在引用的旧对象，坏字节一旦写入
        # 不可恢复，校验必须在 put 之前（2026-08-26 补上原缺失的魔数检查）
        _validate_rendered_png(png)
        storage.put("personal", att.storage_path, png, "image/png")
        att.filename = name
        att.size = len(png)

    fig.prompt = new_prompt
    fig.drawio_xml = drawio_xml
    fig.style = preset["id"]

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


def delete_figure(db: Session, *, storage: Storage, user_id, figure_id: str,
                  force: bool = False) -> None:
    """删除附图（Figure + 关联 Attachment + MinIO 对象，幂等）。

    正文引用防护（2026-08-25）：图已插入正文（章节 content 含其 attachment id）
    时默认 409 拒删并列出引用章节，确认后带 force 重试才真正删除——探测以服务端
    落库内容为准；前端缓存探测只作快速预检（编辑器未保存内容双方都探测不到）。
    """
    fig = get_figure(db, user_id=user_id, figure_id=figure_id)
    if not force:
        refs = find_body_references(db, project_id=fig.project_id,
                                    attachment_id=fig.attachment_id)
        if refs:
            titles = "、".join(f"「{r['section_title']}」" for r in refs)
            raise ConflictError(
                f"检测到图{fig.number}已插入正文章节{titles}，删除后正文中的这张图将失效。"
                "确定要强制删除吗？"
            )
    if fig.attachment_id:
        att = db.get(Attachment, fig.attachment_id)
        if att:
            try:
                storage.delete("personal", att.storage_path)
            except Exception:
                pass
            db.delete(att)
    db.delete(fig)
    db.flush()  # DELETE 先落库（autoflush=False 下 SELECT 看不到未 flush 的删除）
    # 同事务重排：删除后图号前移保持 1..n 连续（与删除原子生效）。
    # 正文的「图K」文字引用不自动改写（V1 原则：编号自动管、自由文本人工核）。
    _renumber_figures(db, fig.project_id)
    db.commit()
