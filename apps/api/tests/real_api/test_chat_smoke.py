"""真实 LLM 冒烟层（批次 F，dsh「inference is cheap here」的中间档）。

与 mock 单测的分工：mock 验证逻辑分支，本层验证「真端点没坏」——
流式产出非空、usage 字段齐全（连带 A-3 缓存命中采集有真数据回归）、
审查评分链路一次真实调用结构合法。断言的是**结构合法性**而非分数。

运行方式（默认被 addopts 排除，显式运行）：
    cd apps/api && uv run pytest -m real_llm

自跳过语义：解析不到全局 chat 配置（CI 无凭据/未配置 LLM）→ 全部 skip，
零维护成本。调真实 API 有小额成本，勿加进任何自动流水线。
"""
import pytest

pytestmark = pytest.mark.real_llm


def _chat_cfg():
    """解析全局 chat 配置；无配置即 skip（本层的自跳过语义）。"""
    from app.core.database import SessionLocal
    from app.services.llm_config_service import resolve_chat_config

    db = SessionLocal()
    try:
        cfg = resolve_chat_config(db, user_id=None)
    finally:
        db.close()
    if cfg is None or not getattr(cfg, "model", None):
        pytest.skip("未配置全局 chat LLM——real_llm 冒烟层自跳过")
    return cfg


def test_stream_chat_smoke_structure():
    """最小聊天调用：流式非空 + usage 字段齐全（A-3 采集链真数据回归）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.ai.llm_client import stream_llm

    cfg = _chat_cfg()
    sink: dict = {}
    chunks: list[str] = []
    messages = [
        SystemMessage(content="你是连通性冒烟探针。"),
        HumanMessage(content="只回复两个字：正常"),
    ]
    for token in stream_llm(messages, llm_config=cfg, usage_sink=sink):
        chunks.append(token)
    text = "".join(chunks)
    assert text.strip(), "流式产出为空"
    assert isinstance(sink.get("prompt"), int) and sink["prompt"] > 0, f"usage 异常：{sink}"
    assert isinstance(sink.get("completion"), int) and sink["completion"] > 0
    # A-3：缓存命中数 provider 不回传时缺键（合法），回显供人工核对趋势
    print(f"\n[real_llm] model={cfg.model} prompt={sink['prompt']} "
          f"completion={sink['completion']} cached={sink.get('cached', 'N/A(未回传)')}")


def test_review_dimension_score_smoke():
    """审查评分链路一次真实调用：返回值结构合法（分数域/证据/建议类型）。"""
    from app.services.review_service import _score_dimension

    cfg = _chat_cfg()
    criterion = {
        "key": "smoke_structure",
        "name": "冒烟·结构完整性",
        "scoring_guide": {
            "90-100": "五个必备部分齐全",
            "60-89": "部分齐全",
            "0-59": "严重缺失",
        },
    }
    sections = {
        "技术领域": "本发明涉及测试技术领域。",
        "技术方案": "本发明提供一种测试方法，包括步骤一与步骤二。",
    }
    score, evidence, suggestion = _score_dimension(criterion, sections, cfg)
    assert isinstance(score, int) and 0 <= score <= 100
    assert isinstance(evidence, str) and evidence.strip()
    assert isinstance(suggestion, str)
    print(f"\n[real_llm] review smoke: score={score} evidence_len={len(evidence)}")
