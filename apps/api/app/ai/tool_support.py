# apps/api/app/ai/tool_support.py
"""自定义配置 tool calling 降级检测（spec Q14-α）。

模型不支持 tool calling → 拒绝服务（抛 ToolSupportError），明确引导用户换模型。
不静默降级（否决项 β，隐性降级是产品事故温床）。
"""

# 已知支持 tool calling 的模型前缀（OpenAI 兼容 function calling）
_KNOWN_SUPPORTED_PREFIXES = (
    "glm-4.5", "glm-4.6", "glm-4.7", "glm-5",
    "deepseek-chat", "deepseek-r1", "deepseek-v",
    "gpt-4", "gpt-5", "claude",
)

# 基础支持但复杂 agent loop 可能不稳（放行但实际表现需观测）
_BASIC_SUPPORTED = ("glm-4-flash", "glm-4-air", "glm-4-plus")


class ToolSupportError(Exception):
    """模型不支持 tool calling，无法启用技能功能。"""


def check_tool_support(*, model: str) -> None:
    """检测模型是否支持 tool calling。不支持抛 ToolSupportError。

    spec Q14-α：拒绝服务而非静默降级。
    """
    if not model:
        raise ToolSupportError(
            "未配置模型，无法启用技能功能。请先在设置中配置支持 function calling 的模型。"
        )

    model_lower = model.lower().strip()

    # 已知完全支持
    for prefix in _KNOWN_SUPPORTED_PREFIXES:
        if model_lower.startswith(prefix):
            return

    # 基础支持（flash/air 等，放行）
    for prefix in _BASIC_SUPPORTED:
        if model_lower.startswith(prefix):
            return

    # 未知模型：保守拒绝（spec Q14-α，宁拒不降级）
    raise ToolSupportError(
        f"当前模型「{model}」不支持 function calling，无法启用技能功能。"
        f"请切换到支持 tool calling 的模型（推荐 glm-4.7 / glm-4.6 / deepseek-chat）。"
    )
