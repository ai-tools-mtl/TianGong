"""会话服务：标题总结等会话相关业务逻辑。"""

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.core.logging import get_logger
from app.models import Conversation

logger = get_logger(__name__)


def summarize_conversation_title(
    db: Session,
    conversation: Conversation,
    first_user_msg: str,
    first_ai_msg: str,
    user_id,
) -> str:
    """用 LLM 根据首条对话内容生成简短标题。失败降级为用户消息前 20 字。

    内部自行 resolve 轻量任务模型配置（resolve_lite_config）：优先用 admin 配的
    轻量模型（典型 GLM-4.7-Flash），未配则回退到该用户的 chat 配置。无配置时
    直接降级，不调 LLM。

    user_id 为会话归属用户，用于在轻量配置未配时回退解析其 chat 配置。
    """
    fallback = first_user_msg[:20] + ("..." if len(first_user_msg) > 20 else "")
    try:
        from langchain_core.messages import HumanMessage

        from app.services.llm_config_service import resolve_lite_config

        llm_config = resolve_lite_config(db, user_id=user_id)
    except Exception:
        logger.warning("标题生成：lite 配置解析失败，降级默认标题")
        return fallback
    if llm_config is None:
        return fallback
    try:
        llm = get_llm(llm_config)
        resp = llm.invoke(
            [
                HumanMessage(
                    content=(
                        "请根据以下对话生成一个简短的中文标题"
                        "（不超过 12 个字，不要引号、不要句号、不要「标题：」前缀）：\n\n"
                        f"用户：{first_user_msg[:500]}\nAI：{first_ai_msg[:500]}\n\n标题："
                    )
                )
            ]
        )
        title = resp.content.strip().strip('“”"\'').strip("。.").strip()[:50]
        return title or fallback
    except Exception:
        logger.warning("标题生成失败，降级默认标题（不影响对话主流程）")
        return fallback
