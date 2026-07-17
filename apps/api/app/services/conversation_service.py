"""会话服务：标题总结等会话相关业务逻辑。"""

from sqlalchemy.orm import Session

from app.models import Conversation


def summarize_conversation_title(
    db: Session,
    conversation: Conversation,
    first_user_msg: str,
    first_ai_msg: str,
    llm_config=None,
) -> str:
    """用 LLM 根据首条对话内容生成简短标题。失败降级为用户消息前 20 字。

    复用 summary_service.generate_summary 的调用模式（同步 invoke + try/except 降级）。
    llm_config 由调用方从 llm_config_service.resolve_llm_config 解析后传入（BYOK 透传）。
    """
    fallback = first_user_msg[:20] + ("..." if len(first_user_msg) > 20 else "")
    try:
        from langchain_core.messages import HumanMessage

        from app.ai.llm_client import get_llm

        llm = get_llm(
            **(
                {
                    "base_url": llm_config.base_url or None,
                    "api_key": llm_config.api_key or None,
                    "model": llm_config.model or None,
                }
                if llm_config
                else {}
            )
        )
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
        return fallback
