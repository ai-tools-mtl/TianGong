"""多模态 vision 支持（设计 §9.5 推迟项的落地）。

提供三个纯函数 + 一个配置解析：
- is_vision_model：按 model 名判断是否支持图片输入（保守名单，漏判只降级不报错）；
  markers 参数供注入 admin 配置的名单（resolve_vision_markers），None 用内置
- resolve_vision_markers：读 SystemSetting vision_model_markers——
  {"enabled": bool, "extra_markers": [str]}，extra 与内置合并；enabled=False
  返回空元组（禁用 vision，全部走文字降级）；无配置/脏数据/异常返回 None（内置）
- build_caption_messages：构造图注润色消息，vision 分支产出多模态 HumanMessage

llm_client.astream_llm 原生支持 list[BaseMessage]，HumanMessage(content=[...])
原生支持多模态 content list，故本模块只负责"消息构造 + 能力探测"，不改 llm_client。
"""

import base64

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

VISION_MARKERS_KEY = "vision_model_markers"

# 已知 vision 模型名片段（小写子串匹配）。
# 刻意保守：非 vision 模型误判为 True 会触发不支持的图片请求导致报错（危险），
# 而漏判只是降级到文字描述（安全方向），故宁可漏判不可误判。
_VISION_MARKERS = (
    "gpt-4o", "gpt-4-vision", "gpt-4-turbo",  # OpenAI
    "claude-3", "claude-sonnet", "claude-opus", "claude-haiku",  # Anthropic
    "gemini",  # Google
    "glm-4v", "glm-4.5v", "glm-4.6v",  # 智谱
    "qwen2-vl", "qwen2.5-vl", "qwen-vl", "qwenvl",  # 通义
    "llava", "minicpm-v", "internvl",  # 开源
    "moonshot-v1-8k-vision", "kimi-vision",  # 月之暗面
    "-vl", "-vision",  # 通用后缀
)


def is_vision_model(model: str | None, markers: tuple[str, ...] | None = None) -> bool:
    """判断 model 名是否（很可能）支持图片输入。保守，漏判安全。

    markers：探测名单（resolve_vision_markers 的返回值）。None 用内置默认；
    空元组 = 显式禁用（恒 False）。
    """
    m = (model or "").lower()
    effective = _VISION_MARKERS if markers is None else markers
    return any(marker in m for marker in effective)


def resolve_vision_markers(db) -> tuple[str, ...] | None:
    """解析生效的 vision 探测名单（admin 可配）。

    返回 None = 无配置，用内置默认（行为与历史版本完全一致）；
    返回 ()  = enabled=False，禁用 vision；
    否则 = 内置 ∪ extra_markers（小写化去空白）。
    任何异常 fail-open 返回 None——配置读取失败不该影响 caption 主流程。
    """
    try:
        from sqlalchemy import select

        from app.models import SystemSetting

        setting = db.scalar(select(SystemSetting).where(
            SystemSetting.key == VISION_MARKERS_KEY))
        stored = setting.value if setting and setting.value else None
        if not isinstance(stored, dict):
            return None
        if not stored.get("enabled", True):
            return ()
        extra = stored.get("extra_markers")
        if not isinstance(extra, list):
            return None
        extras = tuple(
            m.strip().lower() for m in extra if isinstance(m, str) and m.strip())
        return tuple(_VISION_MARKERS) + extras
    except Exception:  # noqa: BLE001 — fail-open 到内置名单
        return None


def build_caption_messages(
    descriptions: list[str],
    images: list[tuple[bytes, str]],  # (图片字节, mime)
    *,
    use_vision: bool,
) -> list[BaseMessage]:
    """构造图注润色消息。

    use_vision=True 且有图 → 多模态（每图一个 image_url content block + 文字说明）；
    否则纯文字降级（与原 caption_figures 行为一致，老测试不破）。
    """
    system = SystemMessage(content=(
        "你是专利交底书撰写助手。请根据提供的附图（及可选的文字描述），"
        "润色生成规范的图注。要求：统一「图 N 是…」格式，简洁准确，"
        "客观描述图示的结构、组成与连接关系，不臆测图中没有的内容。"
    ))
    if use_vision and images:
        content: list[dict] = [
            {"type": "text", "text": "以下是附图，请基于图片内容生成规范图注："}
        ]
        for data, mime in images:
            b64 = base64.b64encode(data).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        if descriptions:
            extra = "\n".join(f"- {d}" for d in descriptions)
            content.append({"type": "text", "text": f"补充文字描述：\n{extra}"})
        return [system, HumanMessage(content=content)]
    # 降级：纯文字
    descs = "\n".join(f"- {d}" for d in descriptions) if descriptions else "（无文字描述）"
    return [system, HumanMessage(content=f"以下是各图的文字描述，请生成规范图注：\n{descs}")]
