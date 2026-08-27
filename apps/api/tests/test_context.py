from app.ai.context_assembler import assemble_messages, SYSTEM_PROMPT
from app.models import Message, Section


def _make_section(key="solution", title="技术方案"):
    return Section(
        template_section_id="ts", order=1, key=key, title=title,
        project_id="00000000-0000-0000-0000-000000000000",
    )


def test_assemble_has_system_prompt():
    section = _make_section()
    msgs = assemble_messages(section, [], user_input="测试")
    assert msgs[0].content.startswith(SYSTEM_PROMPT[:20])


def test_assemble_includes_section_goal():
    section = _make_section("solution")
    msgs = assemble_messages(section, [], user_input="测试")
    assert "技术方案" in msgs[0].content


def test_assemble_includes_completion_criteria():
    """[S1] assemble_messages 路径也注入 completion_criteria（双装配保持一致）。"""
    from app.ai.section_prompts import get_section_prompt
    section = _make_section("solution")
    msgs = assemble_messages(section, [], user_input="测试")
    sp = get_section_prompt("solution")
    assert sp.completion_criteria in msgs[0].content


def test_assemble_includes_guide_questions():
    """[S1] assemble_messages 路径也注入 guide_questions（双装配保持一致）。"""
    from app.ai.section_prompts import get_section_prompt
    section = _make_section("background")
    msgs = assemble_messages(section, [], user_input="测试")
    sp = get_section_prompt("background")
    for q in sp.guide_questions:
        assert q in msgs[0].content


def test_assemble_includes_history():
    section = _make_section()
    history = [
        Message(section_id="x", role="user", content="之前的问题"),
        Message(section_id="x", role="assistant", content="之前的回答"),
    ]
    msgs = assemble_messages(section, history, user_input="新问题")
    assert len(msgs) == 4


def test_assemble_includes_project_summaries():
    section = _make_section()
    summaries = [{"title": "背景技术", "summary": "现有技术不足"}]
    msgs = assemble_messages(section, [], user_input="测试", project_summaries=summaries)
    assert "背景技术" in msgs[0].content
    assert "现有技术不足" in msgs[0].content


# ===== get_written_sections_text 测试 =====

def _tiptap(text: str) -> dict:
    """构造最小 Tiptap JSON（含一段 text）。"""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _make_project(db_session):
    """构造一个真实入库的 Project（含前置 User，满足 user_id NOT NULL 外键）。"""
    from app.models import Project, User
    import uuid
    from app.core.security import hash_password
    u = User(
        username=f"test-{uuid.uuid4().hex[:8]}",
        email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    p = Project(user_id=u.id, title="测试交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _make_db_section(db_session, project_id, *, key, title, order, content=None):
    """构造一个真实入库的 Section。"""
    from app.models import Section
    s = Section(
        project_id=project_id,
        template_section_id=f"ts-{key}",
        order=order, key=key, title=title,
        content=content, status="drafting",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_get_written_sections_text_filters_empty_content(db_session):
    """content 为 None 的章节被跳过。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)  # None，跳过
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("机械领域"))  # 保留
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "技术领域" in text
    assert "发明名称" not in text  # content=None 被跳过


def test_get_written_sections_text_orders_by_section_order(db_session):
    """按 Section.order 排序（不是按插入顺序）。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    # 故意倒序插入
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("BBB"))
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("AAA"))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert text.index("AAA") < text.index("BBB")  # name(order=1) 在 field(order=2) 前


def test_get_written_sections_text_excludes_current_section(db_session):
    """exclude_key 指定的当前章节被排除。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("门锁"))
    text = get_written_sections_text(db_session, p.id, exclude_key="name")
    assert "门锁" not in text
    assert text == ""  # 只有 name，被排除后为空


def test_get_written_sections_text_truncates_at_budget(db_session, monkeypatch):
    """超 8000 字时截断 + 标注「（已截断）」。"""
    from app.ai import context_assembler
    # 把预算调小到 50 字，便于测试
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 50)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    long_text = "X" * 200  # 远超 50 字预算
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap(long_text))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "（已截断）" in text
    assert len(text) <= 200  # 截断后远小于原文 200 字


def test_get_written_sections_text_truncation_keeps_earlier_full(db_session, monkeypatch):
    """截断时前面章节保持完整，当前超长章截断。"""
    from app.ai import context_assembler
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 100)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("短章完整内容"))
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("Y" * 200))  # 超长
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "短章完整内容" in text  # name 完整保留
    assert "（已截断）" in text  # field 被截断


# ===== _format_metadata 测试 =====

def test_format_metadata_str_values():
    """字符串/数字值被格式化为 '- k：v' 行。"""
    from app.ai.context_assembler import _format_metadata
    out = _format_metadata({"技术领域": "机械", "关键词数": 3})
    assert "- 技术领域：机械" in out
    assert "- 关键词数：3" in out


def test_format_metadata_skips_nested_structures():
    """嵌套 dict / list 被跳过（防御性，metadata 结构未定死）。"""
    from app.ai.context_assembler import _format_metadata
    out = _format_metadata({"正常": "值", "嵌套": {"a": 1}, "列表": [1, 2]})
    assert "- 正常：值" in out
    assert "嵌套" not in out
    assert "列表" not in out


def test_format_metadata_empty_returns_empty():
    """空 dict / None 返回空字符串。"""
    from app.ai.context_assembler import _format_metadata
    assert _format_metadata({}) == ""
    assert _format_metadata(None) == ""


# ===== build_system_prompt 测试 =====

def test_build_system_prompt_includes_project_title(db_session):
    """[L4] system prompt 含项目标题。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    p.title = "一种凸轮门锁"
    db_session.commit()
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "一种凸轮门锁" in prompt


def test_build_system_prompt_includes_metadata(db_session):
    """[L4] metadata 非空时被格式化注入。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    p.metadata_ = {"技术领域": "机械", "阶段": "draft"}
    db_session.commit()
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "- 技术领域：机械" in prompt
    assert "- 阶段：draft" in prompt


def test_build_system_prompt_skips_empty_metadata(db_session):
    """[L4] metadata 为 None 时不报错、不留空段。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # metadata_ 默认 None
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "项目背景信息" not in prompt  # 不留空段标题
    assert "测试交底书" in prompt  # 标题仍在


def test_build_system_prompt_includes_current_section_strategy(db_session):
    """含当前章节 goal + output_format。"""
    from app.ai.context_assembler import build_system_prompt
    from app.ai.section_prompts import get_section_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    prompt = build_system_prompt(db_session, s)
    sp = get_section_prompt("solution")
    assert sp.goal in prompt
    assert sp.output_format in prompt
    assert "技术方案" in prompt


def test_build_system_prompt_includes_completion_criteria(db_session):
    """[S1] 含当前章节 completion_criteria（知识资产激活，让模型知道「什么算写完」）。"""
    from app.ai.context_assembler import build_system_prompt
    from app.ai.section_prompts import get_section_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    prompt = build_system_prompt(db_session, s)
    sp = get_section_prompt("solution")
    assert sp.completion_criteria in prompt


def test_build_system_prompt_includes_guide_questions(db_session):
    """[S1] 含当前章节 guide_questions（知识资产激活，引导模型主动追问）。"""
    from app.ai.context_assembler import build_system_prompt
    from app.ai.section_prompts import get_section_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="background", title="背景技术", order=3, content=None)
    prompt = build_system_prompt(db_session, s)
    sp = get_section_prompt("background")
    # guide_questions 非空时，每个问题都应进 prompt
    for q in sp.guide_questions:
        assert q in prompt


def test_build_turn_reminder_includes_written_sections(db_session):
    """[前文注入·批次 A 迁移] 已写章节进易变快照，不进静态 prompt。"""
    from app.ai.context_assembler import build_system_prompt, build_turn_reminder
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("凸轮门锁"))
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    reminder = build_turn_reminder(db_session, s)
    # 快照承载前文（逐轮可变层）
    assert "发明名称" in reminder
    assert "凸轮门锁" in reminder
    # 静态 prompt 不再含前文（prefix cache 决策 D1 的拆分守护）
    assert "凸轮门锁" not in prompt


def test_build_turn_reminder_excludes_current_section_from_written(db_session):
    """快照的已写章节段不含当前章节自身。"""
    from app.ai.context_assembler import build_turn_reminder
    p = _make_project(db_session)
    # 当前章节 field 自己有 content，但不应出现在「已完成章节」段
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("我自己"))
    reminder = build_turn_reminder(db_session, s)
    assert "我自己" not in reminder


# ===== S3-1：前文一致性约束指令（spec 2026-07-29-prompt-content-design §4 S3-1）=====

def test_build_turn_reminder_written_sections_has_consistency_constraints(db_session):
    """[S3-1] 有已写章节时快照注入一致性约束指令（术语/呼应/不矛盾）。

    断言用约束指令的独有特征词（「呼应」「不矛盾」），确保测的是新增指令而非旧文案。
    """
    from app.ai.context_assembler import build_turn_reminder
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="problem", title="技术问题", order=4, content=_tiptap("门锁自动上锁问题"))
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    db_session.commit()
    reminder = build_turn_reminder(db_session, s)
    assert "呼应" in reminder      # 必须呼应前文
    assert "不矛盾" in reminder or "矛盾" in reminder  # 不与前文矛盾


def test_build_turn_reminder_no_written_sections_returns_empty(db_session):
    """[S3-1] 无前文/术语表等易变内容时快照返回空串（调用方跳过包裹标签）。"""
    from app.ai.context_assembler import wrap_user_message, build_turn_reminder
    p = _make_project(db_session)
    # 只有当前章节，无其他非空章节、无检索结果、无意图指令
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    db_session.commit()
    reminder = build_turn_reminder(db_session, s)
    assert "已完成章节" not in reminder
    assert "一致性要求" not in reminder
    # 空快照时包裹函数原样返回，不留空壳 system-reminder 标签
    assert wrap_user_message("原始输入", reminder) == "原始输入"


def test_build_system_prompt_includes_system_prompt_role(db_session):
    """末尾含 SYSTEM_PROMPT 角色定义。"""
    from app.ai.context_assembler import build_system_prompt, SYSTEM_PROMPT
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert SYSTEM_PROMPT in prompt  # 角色定义拼接在末尾


def test_build_system_prompt_first_chapter_no_written(db_session):
    """第一章时跳过「已完成章节」段，不报错。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # 只有当前章节 name，无其他非空章节
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "已完成章节" not in prompt  # 无前文，跳过该段
    assert "测试交底书" in prompt  # 项目标题仍在


# ===== S2-1：章节状态感知注入（spec 2026-07-29-prompt-content-design §4 S2-1）=====

def test_build_system_prompt_status_empty_guides_not_draft(db_session):
    """[S2-1] status=empty 时提示「引导优先、勿急着代写」。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    s.status = "empty"
    db_session.commit()  # 提交状态变更，避免 build_system_prompt 内查询触发 expire 回滚
    prompt = build_system_prompt(db_session, s)
    assert "章节进度" in prompt  # 有专属状态提示段
    assert "空白" in prompt  # empty → 空白章节


def test_build_system_prompt_status_drafting_allows_refine(db_session):
    """[S2-1] status=drafting 时提示「可打磨/修改/答疑」。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    s.status = "drafting"
    db_session.commit()
    prompt = build_system_prompt(db_session, s)
    assert "章节进度" in prompt
    assert "草稿" in prompt  # drafting → 草稿章节


def test_build_system_prompt_status_confirmed_avoids_major_change(db_session):
    """[S2-1] status=confirmed 时提示「默认微调/答疑，避免大改」。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    s.status = "confirmed"
    db_session.commit()
    prompt = build_system_prompt(db_session, s)
    assert "章节进度" in prompt
    assert "定稿" in prompt  # confirmed → 定稿章节


def test_build_system_prompt_status_differentiates_behavior(db_session):
    """[S2-1] empty 与 confirmed 的状态提示必须不同（验证状态真的影响 prompt）。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    s_empty = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    s_empty.status = "empty"
    db_session.commit()
    prompt_empty = build_system_prompt(db_session, s_empty)

    s_confirmed = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    s_confirmed.status = "confirmed"
    db_session.commit()
    prompt_confirmed = build_system_prompt(db_session, s_confirmed)

    # 两个状态的「章节进度」提示行必须不同
    assert "空白" in prompt_empty and "空白" not in prompt_confirmed
    assert "定稿" in prompt_confirmed and "定稿" not in prompt_empty


# ===== S2-2：意图识别注入（批次 A 迁移：意图指令随当轮快照，不进静态 prompt）=====

def test_build_turn_reminder_intent_draft_instructs_to_write(db_session):
    """[S2-2] intent=draft 时快照注入「代写」行为指令。"""
    from app.ai.context_assembler import build_system_prompt, build_turn_reminder
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    db_session.commit()
    reminder = build_turn_reminder(db_session, s, intent="draft")
    assert "代写" in reminder
    # 静态 prompt 不含意图段（逐轮变化层，决策 D1）
    assert "直接产出结构化内容" not in build_system_prompt(db_session, s)


def test_build_turn_reminder_intent_info_instructs_to_answer(db_session):
    """[S2-2] intent=info 时快照注入「答疑」行为指令，避免借机代写。"""
    from app.ai.context_assembler import build_turn_reminder
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    db_session.commit()
    reminder = build_turn_reminder(db_session, s, intent="info")
    assert "答疑" in reminder or "问问题" in reminder


def test_build_turn_reminder_intent_none_has_no_intent_section(db_session):
    """[S2-2] intent=none（默认/未识别）时快照不含意图指令段。"""
    from app.ai.context_assembler import build_turn_reminder
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    db_session.commit()
    reminder_default = build_turn_reminder(db_session, s)
    reminder_none = build_turn_reminder(db_session, s, intent="none")
    assert "直接产出结构化内容" not in reminder_default  # draft 指令特征
    assert "不要借机代写" not in reminder_default          # info 指令特征
    assert "直接产出结构化内容" not in reminder_none
    assert "不要借机代写" not in reminder_none


def test_build_turn_reminder_intent_differentiates(db_session):
    """[S2-2] draft 与 info 的意图指令必须不同（验证意图真的影响快照）。"""
    from app.ai.context_assembler import build_turn_reminder
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    db_session.commit()
    reminder_draft = build_turn_reminder(db_session, s, intent="draft")
    reminder_info = build_turn_reminder(db_session, s, intent="info")
    assert reminder_draft != reminder_info


# ===== S4-1：few-shot 范例注入（spec 2026-07-29-prompt-content-design §4 S4-1）=====

def test_build_system_prompt_includes_few_shot_example(db_session):
    """[S4-1] build_system_prompt 注入当前章节的 few_shot_example 范例。"""
    from app.ai.context_assembler import build_system_prompt
    from app.ai.section_prompts import get_section_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="background", title="背景技术", order=3, content=None)
    db_session.commit()
    prompt = build_system_prompt(db_session, s)
    sp = get_section_prompt("background")
    assert sp.few_shot_example in prompt


def test_build_system_prompt_omits_few_shot_when_none(db_session):
    """[S4-1] 章节无范例时（如 custom）不注入范例段。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # custom 章节无专属范例
    s = _make_db_section(db_session, p.id, key="custom", title="自定义章节", order=99, content=None)
    db_session.commit()
    prompt = build_system_prompt(db_session, s)
    # 无范例时不出现「参考范例」段
    assert "参考范例" not in prompt
