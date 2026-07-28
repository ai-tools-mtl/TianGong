"""G2 admin 检索测试端点（spec §5.2）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.rag.retriever import retrieve, SIMILARITY_THRESHOLD

router = APIRouter(tags=["admin"])  # 空 prefix：项目约定（路径字面量写装饰器）


class RetrievalTestRequest(BaseModel):
    query: str
    top_k: int = 5
    scope: str | None = None  # None / "global" / "personal"


@router.post("/admin/knowledge/retrieval-test")
def retrieval_test(
    payload: RetrievalTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 检索测试：返回召回结果 + 当前配置参数，供 RAG 调参闭环验证。"""
    results = retrieve(
        db, user_id=admin.id, query=payload.query, top_k=payload.top_k, scope=payload.scope
    )
    return {
        "results": [
            {
                "content": r.content[:500],
                "score": round(r.score, 3),
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ],
        "threshold": SIMILARITY_THRESHOLD,
        "top_k": payload.top_k,
        "scope": payload.scope,
    }
