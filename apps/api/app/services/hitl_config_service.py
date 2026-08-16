"""HITL（工具调用人工确认）配置服务。

admin 可配置哪些 agent 工具在执行前需要用户确认（如 generate_figure——
LLM + drawio 渲染较贵）。存储模式照 figure_preset_service：单行
SystemSetting（key=agent_hitl_config），value = {"enabled": bool, "tools": [str]}。

无配置时取默认：enabled=True、tools=["generate_figure"]。
interrupt 依赖 checkpointer 持久化断点——build_agent 在 checkpointer 为 None
（初始化失败 fail-open）时自动放弃 HITL（无断点可停，宁可不拦也不挂死）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting

HITL_CONFIG_KEY = "agent_hitl_config"

# 默认拦截清单：只拦昂贵工具。rag_search/save_memory 只读/轻量，不打扰。
DEFAULT_HITL_CONFIG: dict = {"enabled": True, "tools": ["generate_figure"]}

# 决策类型：V1 只放行 approve/reject（edit/respond 前端无编辑 UI，不开）。
ALLOWED_DECISIONS = ["approve", "reject"]

# 工具名 → 展示给用户的确认说明（interrupt 事件 description 字段）
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "generate_figure": "生成专利附图会调用 LLM 并渲染图片（较耗时），请确认是否执行",
}


def get_hitl_config(db: Session) -> dict:
    """读取生效的 HITL 配置（SystemSetting 覆盖默认；缺省/脏数据回退默认）。"""
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == HITL_CONFIG_KEY))
    stored = setting.value if setting and setting.value else None
    if not isinstance(stored, dict):
        return dict(DEFAULT_HITL_CONFIG)
    enabled = bool(stored.get("enabled", DEFAULT_HITL_CONFIG["enabled"]))
    tools = stored.get("tools")
    if not isinstance(tools, list) or not all(isinstance(t, str) and t.strip() for t in tools):
        tools = DEFAULT_HITL_CONFIG["tools"]
    return {"enabled": enabled, "tools": [t.strip() for t in tools]}


def set_hitl_config(db: Session, *, enabled: bool, tools: list[str], updated_by=None) -> dict:
    """保存 HITL 配置（全量覆盖）。tools 为工具名列表（MCP 工具按名配置）。"""
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == HITL_CONFIG_KEY))
    value = {"enabled": enabled, "tools": [t.strip() for t in tools if t.strip()]}
    if setting:
        setting.value = value
        setting.updated_by = updated_by
    else:
        db.add(SystemSetting(key=HITL_CONFIG_KEY, value=value, updated_by=updated_by))
    db.commit()
    return get_hitl_config(db)


def build_interrupt_on(db: Session, *, checkpointer) -> dict | None:
    """生成 create_deep_agent 的 interrupt_on 参数；不拦截时返回 None。

    interrupt_on 条目结构（deepagents 0.6.12 / langchain InterruptOnConfig）：
    {tool_name: {"allowed_decisions": ["approve", "reject"], "description": str}}。
    checkpointer 为 None 时返回 None（HITL 断点无法持久化，不能拦）。
    """
    if checkpointer is None:
        return None
    cfg = get_hitl_config(db)
    if not cfg["enabled"] or not cfg["tools"]:
        return None
    return {
        tool: {
            "allowed_decisions": list(ALLOWED_DECISIONS),
            "description": _TOOL_DESCRIPTIONS.get(tool, f"工具 {tool} 需要确认后执行"),
        }
        for tool in cfg["tools"]
    }
