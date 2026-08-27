"""单 turn token 预算配置服务（借鉴机制批次 A-4）。

存储模式照 hitl_config_service：单行 SystemSetting（key=agent_turn_token_budget），
value = {"budget": int}。

语义：
- budget > 0：单 turn 累计（prompt+completion，多步 agent loop 逐步累加）超过该值时
  温和收束（向 loop 注入收尾提示后停止消费后续事件），消息标 meta.budget_capped。
- budget <= 0 或 value 显式为 {"budget": 0}：关闭熔断。
- 无配置：取 DEFAULT_TURN_TOKEN_BUDGET（宽松值，兜住失控敞口而非正常长会话——
  正常多轮 turn 的真实分布在 eval/dogfood 数据出来后再校准）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting

TURN_TOKEN_BUDGET_KEY = "agent_turn_token_budget"

# 默认上限：正常场景（10 轮内对话 + 工具调用）远达不到；失控循环可在秒级烧穿它。
# 数字来源：DeepSeek 单请求上下文 128k，重复工具循环每步重发全上下文，
# 300k ≈ 3 个完整请求的量级即可判定为失控，正常流永不误伤。
DEFAULT_TURN_TOKEN_BUDGET = 300_000


def get_turn_token_budget(db: Session) -> int:
    """读取生效的单 turn token 预算（0 = 关闭熔断）。脏数据回退默认。"""
    setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == TURN_TOKEN_BUDGET_KEY)
    )
    stored = setting.value if setting and setting.value else None
    if not isinstance(stored, dict):
        return DEFAULT_TURN_TOKEN_BUDGET
    raw = stored.get("budget", DEFAULT_TURN_TOKEN_BUDGET)
    if not isinstance(raw, int) or isinstance(raw, bool):
        return DEFAULT_TURN_TOKEN_BUDGET
    return max(raw, 0)


def set_turn_token_budget(db: Session, *, budget: int, updated_by=None) -> int:
    """保存预算配置（全量覆盖）。budget <= 0 表示关闭。"""
    setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == TURN_TOKEN_BUDGET_KEY)
    )
    value = {"budget": max(int(budget), 0)}
    if setting:
        setting.value = value
        setting.updated_by = updated_by
    else:
        db.add(SystemSetting(key=TURN_TOKEN_BUDGET_KEY, value=value, updated_by=updated_by))
    db.commit()
    return get_turn_token_budget(db)
