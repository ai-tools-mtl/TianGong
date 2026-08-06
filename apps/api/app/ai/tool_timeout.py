"""工具调用超时防护 middleware（层 1：单次工具级超时）。

通过 langchain AgentMiddleware.awrap_tool_call 钩子拦截每一次工具执行，
套 asyncio.wait_for。超时返回 ToolMessage(status="error")，让 LLM 看到
error 后自行绕过该工具继续生成——而非让 agent loop 永久死等。

三层防护中的核心层，覆盖所有工具（内置 rag_search/save_memory + MCP 外部工具 +
deepagents 内置 fs/execute），因为它们都走同一个 ToolNode → awrap_tool_call 链。

技术细节：
- MCP 工具是纯 async（StructuredTool coroutine=），wait_for 超时可干净取消。
- 内置工具是同步 def，deepagents 经 run_in_executor 扔线程池；wait_for 超时只放弃
  等待 Future，线程仍在跑（Python 无法强杀线程），但 agent loop 已解锁。可接受——
  同步工具内部已有 HTTP 超时（NLI 3s / rerank 15s），真挂的概率低，且线程泄漏次数
  受限（每次对话工具调用次数有限）。

参考实现：langchain/agents/middleware/tool_retry.py 的 awrap_tool_call 结构。
"""
import asyncio
import logging

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp

logger = logging.getLogger(__name__)

# 单轮 agent loop（含多步工具调用 + 生成）总超时上限（层 3 用）。
# 正常对话+几次工具+生成通常 30-60s，120s 是宽松兜底防极端情况无限循环。
AGENT_LOOP_TOTAL_TIMEOUT = 120.0


class ToolTimeoutMiddleware(AgentMiddleware):
    """单次工具调用超时防护。

    分类超时（按工具来源）：
    - 内置工具（rag_search/save_memory）：TOOL_TIMEOUTS 查表
    - MCP / 外部工具（不在 BUILTIN_TOOLS 内）：MCP_DEFAULT_TIMEOUT（更宽松）
    - 其它内置（deepagents fs/execute 等）：BUILTIN_FALLBACK_TIMEOUT
    """

    # 内置工具分类超时表（秒）。
    TOOL_TIMEOUTS: dict[str, float] = {
        "rag_search": 15.0,   # 串了 embed + rerank，15s 足够覆盖慢网络
        "save_memory": 10.0,  # DB 写 + 可能的 NLI(3s)，10s 足够
    }
    MCP_DEFAULT_TIMEOUT = 20.0        # MCP 外部进程，给更宽松的余量
    BUILTIN_FALLBACK_TIMEOUT = 15.0   # 未在 TOOL_TIMEOUTS 里的内置工具

    async def awrap_tool_call(self, request, handler):
        """拦截每一次工具调用，套 asyncio.wait_for 超时。

        超时 → 返回 ToolMessage(status="error")，让 agent 继续而非死等。
        GraphBubbleUp（interrupt 等控制流信号）必须透传，不能被超时吞掉。
        其它异常不在此处理——ToolNode 自带的 handle_tool_errors 会接。
        """
        tool_name = request.tool.name if request.tool else request.tool_call["name"]
        timeout = self._resolve_timeout(tool_name)
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout)
        except GraphBubbleUp:
            raise  # 控制流信号（interrupt / parent command）必须透传
        except asyncio.TimeoutError:
            logger.warning(
                "工具 %s 执行超时（%ss），返回 error 让 agent 继续",
                tool_name, timeout,
            )
            return ToolMessage(
                content=(
                    f"工具 {tool_name} 执行超时（{timeout}s），未能完成。"
                    f"请基于现有信息继续回答，不要再次调用此工具。"
                ),
                tool_call_id=request.tool_call["id"],
                name=tool_name,
                status="error",
            )

    def _resolve_timeout(self, tool_name: str) -> float:
        """按工具名解析超时阈值：内置工具查表，MCP/外部工具用宽松默认。"""
        from app.ai.tools import BUILTIN_TOOLS

        if tool_name in self.TOOL_TIMEOUTS:
            return self.TOOL_TIMEOUTS[tool_name]
        if tool_name not in BUILTIN_TOOLS:
            return self.MCP_DEFAULT_TIMEOUT  # MCP / 外部插件工具
        return self.BUILTIN_FALLBACK_TIMEOUT
