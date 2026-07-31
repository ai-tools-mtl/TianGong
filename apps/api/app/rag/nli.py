"""NLI 矛盾判断模块（spec §5）。

⚠️【2026-07-31 实测发现设计缺陷，矛盾覆盖已临时禁用】
原设计调本地 Infinity 容器的 /classify 端点跑 cross-encoder NLI 小模型。
但实测 Infinity 0.0.77 的 /classify 只支持单句分类（ClassifyInput.input 是
conlist(str)，路由 engine.classify(sentences=...) 把每句独立分类），**不支持
NLI 必需的 [premise, hypothesis] 句子对配对输入**——传 ["偏好简洁","偏好详尽"]
会被当两条独立句子各判 neutral，永远拿不到 contradiction。

故当前矛盾覆盖**默认禁用**（CONTRADICTION_OVERRIDE_ENABLED = False），
judge_relation 直接返回 "neutral"，save_memory 退回纯合并不删。
热度/淘汰功能不受影响，照常工作。

后续恢复方案（待选型）：
1. 自建轻量 FastAPI 微服务用 sentence-transformers CrossEncoder 原生加载
   nli-deberta-v3-base，提供支持句子对的 /nli 端点（推荐，0 token）
2. 改用 chat LLM 判矛盾（耗 token）
3. 确认 Infinity 新版本是否支持 pair 输入

恢复时把 CONTRADICTION_OVERRIDE_ENABLED 改 True 并接通真实 pair 输入即可。
"""
import httpx

from app.core.config import get_settings

# 矛盾覆盖总开关。默认 False：Infinity /classify 不支持句子对，禁用避免误判。
# 详见模块 docstring 的设计缺陷说明。
CONTRADICTION_OVERRIDE_ENABLED = False


def judge_relation(premise: str, hypothesis: str) -> str:
    """判定两段文本关系：contradiction / entailment / neutral。

    语义层判断（两句话能否同时为真），用于矛盾覆盖决策。

    当前默认禁用（CONTRADICTION_OVERRIDE_ENABLED=False），直接返回 "neutral"，
    save_memory 退回纯合并不删。详见模块 docstring。

    启用后：服务不可用/超时/异常时返回 "neutral"（降级，绝不误删）。
    """
    if not CONTRADICTION_OVERRIDE_ENABLED:
        return "neutral"

    try:
        base_url = get_settings().nli_base_url
        resp = httpx.post(
            f"{base_url}/classify",
            json={"inputs": [[premise, hypothesis]]},
            timeout=2.0,
        )
        resp.raise_for_status()
        # Infinity 返回 [[{"label":"contradiction","score":0.9}, ...]]
        scores = resp.json()[0]
        top = max(scores, key=lambda x: x["score"])
        return top["label"]   # contradiction / entailment / neutral
    except Exception:
        return "neutral"      # 降级：绝不误判矛盾
