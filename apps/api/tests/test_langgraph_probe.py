# apps/api/tests/test_langgraph_probe.py
"""HITL 探针（spec §3.1.3 / T2 计划批 1 Task 0.1）：钉死 langgraph 对
「checkpointer 非 None + astream_events 无 thread_id」的行为。

背景（源码已核验）：orchestrator 三路 build_agent 均传 get_checkpointer()
（orchestrator.py:243/:310/:357），interrupt_on 由 checkpointer 推导（agent.py:176）；
generate 端点无 thread_id（_astream_agent_events 里 config=None）。

探针结论（2026-08-17，当前 langgraph 版本，原生图 + deepagents 图双重复现）：
1. 【坐实·比 spec 预想严重】图带 checkpointer 且 config=None（无 configurable）时，
   astream_events 在**入口级无条件抛** `ValueError: Checkpointer requires one or
   more of the following 'configurable' keys: thread_id, checkpoint_ns, checkpoint_id`
   （langgraph/pregel/main.py:2589 的入口检查，与是否触发 interrupt 无关）。
   推论：generate 端点自 2026-08-13 checkpoint 合并起，在 PG 环境（checkpointer
   初始化成功）下**每次调用都以 llm_error 告终**——chat/resume 因传 thread_id 幸免，
   generate 是 config=None 的唯一 agent loop 路径。单测未暴露：test_orchestrator 全
   mock build_agent，不走真 langgraph 入口。
   → 批 1 Task 1.5 修复（紧急）：generate 去 checkpointer（generate 无 resume 能力，
   checkpointer 零收益）；revise 按设计不传 checkpointer。
2. 【顺带观察】astream_events(version='v2') 对原生 StateGraph 的 interrupt 不 emit
   `on_interrupt` 事件（interrupt 挂起只出现在 astream(stream_mode='updates') 的
   __interrupt__ 块）。生产 orchestrator 的 on_interrupt 监听在 deepagents 路径有效
   （HITL 卡片已验证）——deepagents middleware interrupt 与原生图事件形态不同。
3. 【恢复语义】interrupt() 返回 Command(resume=X) 的 X 原样值。

结论同记 docs/GOTCHAS.md。本测试是升级 langgraph 时的回归警报。
"""
import asyncio

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt


def _build_probe_graph(checkpointer):
    """最小图：单节点内 interrupt()，模拟 HumanInTheLoopMiddleware 的挂起语义。"""
    builder = StateGraph(dict)

    def node(state):
        answer = interrupt({"question": "allow?"})
        return {"done": answer}

    builder.add_node("n", node)
    builder.set_entry_point("n")
    builder.add_edge("n", END)
    return builder.compile(checkpointer=checkpointer)


def test_probe_with_thread_id_interrupt_hangs_and_resumes():
    """对照实验：带 thread_id + checkpointer → interrupt 正常挂起 + Command(resume) 恢复。

    检测用 astream(stream_mode='updates') 的 __interrupt__ 块（见模块 docstring 结论 2：
    astream_events v2 对原生图不发 on_interrupt）。
    """
    graph = _build_probe_graph(InMemorySaver())
    tid = "probe-tid"

    async def drain():
        chunks = []
        async for chunk in graph.astream({"messages": []}, config={"configurable": {"thread_id": tid}},
                                         stream_mode="updates"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(drain())
    assert any("__interrupt__" in c for c in chunks), "带 thread_id 时 interrupt 必须挂起"

    async def resume():
        out = []
        async for chunk in graph.astream(
            Command(resume={"answer": "yes"}), config={"configurable": {"thread_id": tid}},
            stream_mode="values",
        ):
            out.append(chunk)
        return out

    states = asyncio.run(resume())
    # 结论 3：interrupt() 返回 resume 值原样（{'answer': 'yes'} 整体），非解包字段
    assert states and states[-1].get("done") == {"answer": "yes"}


def test_probe_without_thread_id_raises_value_error_unconditionally():
    """【坐实 generate 全坏根因】checkpointer 非 None + config=None → 入口级无条件 ValueError。

    与节点是否调 interrupt() 无关（对照下一个测试）。这是 langgraph 的入口检查，
    不是 interrupt 触发时的错误——generate 端点（config=None 唯一 agent loop 路径）
    在 checkpointer 初始化成功的环境下每次调用都撞上它。
    """
    graph = _build_probe_graph(InMemorySaver())

    async def drain():
        try:
            async for _ in graph.astream_events({"messages": []}, version="v2", config=None):
                pass
        except ValueError as e:
            return str(e)
        return None

    msg = asyncio.run(drain())
    assert msg is not None, "langgraph 行为变化：config=None + checkpointer 不再抛 ValueError"
    assert "thread_id" in msg, f"错误消息变化：{msg}"


def test_probe_no_interrupt_node_still_raises():
    """节点完全不调 interrupt() 的图，config=None + checkpointer 同样抛 ValueError——
    坐实「入口级」检查（非 interrupt 触发）。"""
    builder = StateGraph(dict)
    builder.add_node("n", lambda state: {"done": "ok"})
    builder.set_entry_point("n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    async def drain():
        try:
            async for _ in graph.astream_events({"x": 1}, version="v2", config=None):
                pass
        except ValueError:
            return "raised"
        return "ran"

    assert asyncio.run(drain()) == "raised"


def test_probe_config_none_without_checkpointer_runs_normally():
    """checkpointer=None（revise 采用的方式）+ config=None → 正常运行、无任何检查。"""
    builder = StateGraph(dict)
    builder.add_node("n", lambda state: {"done": "ok"})
    builder.set_entry_point("n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=None)  # revise 路径：显式不传

    async def drain():
        ran = False
        async for _ in graph.astream_events({"x": 1}, version="v2", config=None):
            ran = True
        return ran

    assert asyncio.run(drain()) is True
