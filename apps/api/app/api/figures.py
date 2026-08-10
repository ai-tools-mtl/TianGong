"""专利附图 AI 生成路由。

照 attachments.py（非流式 CRUD）+ caption_figures（含 chat_source 的 LLM 端点）。
端点：
  POST   /sections/{section_id}/figures/generate  生成附图
  GET    /projects/{project_id}/figures           列出项目附图
  GET    /figures/{figure_id}                     附图详情（含 drawio XML 源）
  POST   /figures/{figure_id}/regenerate          重新生成（替换 PNG）
  DELETE /figures/{figure_id}                     删除附图

渲染产物 PNG 复用现有 Attachment 下载端点（GET /projects/{id}/attachments/{aid}/file），
前端用 attachmentUrl(project_id, figure.attachment_id) 拼图地址。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import get_storage
from app.deps import get_current_user
from app.models import User
from app.services import figure_service

router = APIRouter(tags=["figures"])


class GenerateRequest(BaseModel):
    """生成附图请求。"""
    prompt: str = Field(..., min_length=1, max_length=2000, description="附图描述")
    diagram_type: str | None = Field(None, description="图类型：flowchart/architecture/sequence/...")
    chat_source: str | None = Field(None, description="LLM 源（前端 getChatDefaultSource 返回值）")
    style: str = Field("patent-bw", description="风格预设：patent-bw/clean-color/technical")


class RegenerateRequest(BaseModel):
    """重新生成附图请求。prompt 缺省时复用原 prompt。"""
    prompt: str | None = Field(None, max_length=2000)
    chat_source: str | None = None
    style: str | None = Field(None, description="风格预设，None 时复用原值")


@router.post("/sections/{section_id}/figures/generate", status_code=201)
def generate(
    section_id: str,
    payload: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成一张专利附图（LLM 出 drawio XML → 渲染 PNG → 落库）。"""
    fig = figure_service.generate_figure(
        db, storage=get_storage(), user_id=current_user.id, section_id=section_id,
        prompt=payload.prompt, diagram_type=payload.diagram_type, chat_source=payload.chat_source,
        style=payload.style,
    )
    return figure_service._to_figure_out(fig, project_id=str(fig.project_id))


@router.get("/projects/{project_id}/figures")
def list_figures(
    project_id: str,
    section_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目的附图。"""
    figs = figure_service.list_figures(
        db, user_id=current_user.id, project_id=project_id, section_id=section_id,
    )
    return [figure_service._to_figure_out(f, project_id=project_id) for f in figs]


@router.get("/figures/{figure_id}")
def get_figure(
    figure_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """附图详情（含 drawio XML 源）。"""
    fig = figure_service.get_figure(db, user_id=current_user.id, figure_id=figure_id)
    return figure_service._to_figure_detail(fig)


@router.post("/figures/{figure_id}/regenerate")
def regenerate(
    figure_id: str,
    payload: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重新生成附图（替换 PNG，更新 XML 源与 prompt）。"""
    fig = figure_service.regenerate_figure(
        db, storage=get_storage(), user_id=current_user.id, figure_id=figure_id,
        prompt=payload.prompt, chat_source=payload.chat_source, style=payload.style,
    )
    return figure_service._to_figure_out(fig, project_id=str(fig.project_id))


@router.delete("/figures/{figure_id}", status_code=204)
def delete_figure(
    figure_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除附图（Figure + 关联 Attachment + MinIO 对象）。"""
    figure_service.delete_figure(
        db, storage=get_storage(), user_id=current_user.id, figure_id=figure_id,
    )
    return None
