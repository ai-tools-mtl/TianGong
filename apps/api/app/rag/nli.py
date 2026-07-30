"""NLI 矛盾判断模块（spec §5）：调本地 Infinity 容器跑 cross-encoder NLI 小模型。

复用 embedding 服务的部署范式（Infinity 镜像 + 本地模型 + 只读挂载），
区别：NLI 是 sequence-classification 任务，走 /classify 端点（非 /embeddings）。

核心安全阀：服务不可用/超时/异常一律返回 "neutral"（降级为相似补充，走原合并逻辑），
绝不误判矛盾导致误删。失败必须向安全方向倾斜。
"""
import httpx

from app.core.config import get_settings


def judge_relation(premise: str, hypothesis: str) -> str:
    """判定两段文本关系：contradiction / entailment / neutral。

    语义层判断（两句话能否同时为真），用于矛盾覆盖决策。
    服务不可用/超时/异常时返回 "neutral"（降级，绝不误删）。
    """
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
