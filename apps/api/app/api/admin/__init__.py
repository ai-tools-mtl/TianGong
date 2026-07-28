"""管理员 API 包：聚合 admin 域 4 个子 router + 暴露统一 router。

从原单文件 admin.py（682 行）拆出（refactor/admin-api-split）。包含：
- admin/users.py       用户运营域（/admin/users/*）
- admin/console.py     系统控制台（/admin/llm-config + /admin/stats/* + /admin/audit-logs）
- admin/content.py     内容生产（/admin/content/templates/* + /admin/knowledge/upload）
- admin/review.py      知识库审核（/admin/knowledge/reviews/*）
- admin/retrieval.py   检索测试（/admin/knowledge/retrieval-test，G2 RAG 调参闭环）

注：用户自定义配置（/settings/*）拆到 app/api/settings.py，不属本包。

子 router 都用 tags=["admin"]、空 prefix（路径字面量写在装饰器上，与原 admin.py 一致）。
聚合后保持 API 契约零变化（URL/tags/响应结构全不变）。

include 顺序：子 router 间的路径冲突已无（不同前缀），但子 router 内部
的路由顺序约束（如 {user_id} 必须在 recent-logins 后）在各子文件内已保证。
"""

from fastapi import APIRouter

from . import console, content, invites, retrieval, review, skills, users

router = APIRouter(tags=["admin"])
router.include_router(users.router)
router.include_router(console.router)
router.include_router(content.router)
router.include_router(review.router)
router.include_router(skills.router)
router.include_router(invites.router)
router.include_router(retrieval.router)
