"""会话服务：标题总结等会话相关业务逻辑。"""

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.models import Conversation
from app.services.llm_config_service import ResolvedLLMConfig


def summarize_conversation_title(
    db: Session,
    conversation: Conversation,
    first_user_msg: str,
    first_ai_msg: str,
    llm_config: ResolvedLLMConfig | None = None,
) -> str:
    """用 LLM 根据首条对话内容生成简短标题。失败降级为用户消息前 20 字。

    llm_config 由调用方从 llm_config_service.resolve_llm_config 解析后传入。
    无配置（None）时直接降级，不调 LLM。

    F1 修复：原代码 get_llm(**{base_url,api_key,model}) 传错参数（get_llm 期望
    ResolvedLLMConfig 位置参数），TypeError 被 except Exception 吞掉，标题摘要
    始终静默 fallback。改为直接传 llm_config。
    """
    fallback = first_user_msg[:20] + ("..." if len(first_user_msg) > 20 else "")
    if llm_config is None:
        return fallback
    try:
        from langchain_core.messages import HumanMessage

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
        return fallback
