"""LLM 错误友好化（共享）。

从 app/api/ai.py 抽出，供 SSE 端点（api/ai.py）与测试连接（llm_config_service.test_llm_connection）共用，
避免逻辑分裂。覆盖智谱 GLM / OpenAI 兼容协议常见错误码：
- 1214 / "model code cannot be empty" / get_llm 的 ValueError「缺少 model」→ 提示补模型名
- 1002 / 401 / Authorization / Invalid API Key → 提示查 Key
- JSON 解析失败（Expecting value / JSONDecodeError）→ 提示检查 API 地址和密钥
- 超时 / 连接 → 提示网络
未匹配保留 str(e)（截断 200），不丢信息。
"""

import logging

logger = logging.getLogger("tiangong.llm")


def friendly_llm_error(e: Exception) -> str:
    """把 LLM provider 原始异常转成中文友好提示。"""
    msg = str(e)
    # 1214：model 为空（含上游 get_llm 的 ValueError「缺少 model」）
    if "1214" in msg or "model code cannot be empty" in msg or "缺少 model" in msg:
        return "LLM 配置缺少模型名，请前往设置补全「模型」字段"
    # 1002 / key 非法 / 401
    if "1002" in msg or "Authorization" in msg or "API Key" in msg or "Invalid API Key" in msg:
        return "API Key 无效或已过期，请前往设置检查密钥"
    # JSON 解析失败：base_url 指向非 API 端点（返回 HTML / 空响应）时，
    # langchain_openai 内部 httpx → json.loads 抛 JSONDecodeError。
    # 常见场景：base_url 拼错、缺 /v1 尾段、目标不是 OpenAI 兼容端点、
    # stream_usage 导致 provider 返回非标准响应等。
    if "Expecting value" in msg or "JSONDecodeError" in msg or "Expecting property name" in msg:
        logger.warning(
            "LLM JSON 解析失败（通常因 base_url 指向非 API 端点或 provider 返回非 JSON）: %s",
            msg[:300],
        )
        return (
            "LLM 服务返回了无效响应，请检查 API 地址和密钥配置是否正确。"
            "常见原因：1) base_url 拼写或路径错误；2) 目标地址不是 OpenAI 兼容端点；"
            "3) API Key 无效导致服务端返回 HTML 错误页。"
            "可到「设置 → LLM 配置 → 测试连接」验证连通性"
        )
    # 超时 / 连接
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "LLM 请求超时，请稍后重试"
    if "connection" in msg.lower() or "unreachable" in msg.lower():
        return "无法连接 LLM 服务，请检查网络或 base_url"
    return msg[:200]
