"""NLI 矛盾判断模块（spec §5）：调自建 NLI 微服务跑 cross-encoder NLI 小模型。

微服务（apps/nli/，端口 7999）用 sentence-transformers 的 CrossEncoder 原生加载
cross-encoder/nli-deberta-v3-base，提供支持 [premise, hypothesis] 句子对配对的 /nli 端点。
这是 NLI 的正确用法——CrossEncoder.predict([(p,h)]) 把两句话作为一对送入 cross-encoder，
输出 contradiction / entailment / neutral。

为何不用 Infinity：Infinity 的 /classify 只支持单句分类（ClassifyInput.input 是
conlist(str)），不支持 NLI 必需的句子对配对输入。

核心安全阀：服务不可用/超时/异常一律返回 "neutral"（降级为相似补充，走原合并逻辑），
绝不误判矛盾导致误删。失败必须向安全方向倾斜。
"""
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 矛盾覆盖总开关。默认 True：自建 NLI 微服务（apps/nli/）已就绪，支持真实句子对推理。
# 关闭时 judge_relation 直接返回 neutral，save_memory 退回纯合并不删。
CONTRADICTION_OVERRIDE_ENABLED = True


def judge_relation(premise: str, hypothesis: str) -> str:
    """判定两段文本关系：contradiction / entailment / neutral。

    语义层判断（两句话能否同时为真），用于矛盾覆盖决策。
    服务不可用/超时/异常时返回 "neutral"（降级，绝不误删）。
    """
    if not CONTRADICTION_OVERRIDE_ENABLED:
        return "neutral"

    try:
        base_url = get_settings().nli_base_url
        resp = httpx.post(
            f"{base_url}/nli",
            json={"premise": premise, "hypothesis": hypothesis},
            timeout=3.0,  # 模型已预热，CPU 单次毫秒级；留余量给冷启动/排队
        )
        resp.raise_for_status()
        # 自建微服务返回扁平 {"label": "...", "score": ...}
        return resp.json()["label"]   # contradiction / entailment / neutral
    except Exception:
        # 降级 neutral（绝不误判矛盾）。补 warning 留痕——否则 NLI 微服务挂了
        # 系统静默退回纯合并，运维以为矛盾覆盖还在生效却无从察觉。
        logger.warning("NLI 服务不可用，降级为 neutral", exc_info=True)
        return "neutral"
