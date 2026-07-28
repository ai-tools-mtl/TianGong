"""diff_service 单元测试（纯函数 + Tiptap 集成）。

覆盖：
- compute_section_diff：空原文、相同、替换、插入、删除、多 hunk
- merge_accepted_hunks：全接受、全不接受、部分接受
- apply_diff_to_section：乐观锁冲突、成功写入 Tiptap JSON
"""

import pytest

from app.services.diff_service import (
    Hunk,
    _hunk_id,
    compute_section_diff,
    merge_accepted_hunks,
)


# ---------- compute_section_diff ----------


def test_compute_diff_empty_original_treated_as_insert():
    """原文为空 → 整个 ai_text 视为 insert。"""
    hunks = compute_section_diff("", "hello world")
    assert len(hunks) == 1
    assert hunks[0].type == "insert"
    assert hunks[0].text == "hello world"
    assert hunks[0].id == _hunk_id("insert", "", "hello world")


def test_compute_diff_empty_ai_treated_as_delete():
    """ai_text 为空 → 整个 original 视为 delete。"""
    hunks = compute_section_diff("original text", "")
    assert len(hunks) == 1
    assert hunks[0].type == "delete"
    assert hunks[0].original_para == "original text"


def test_compute_diff_identical_returns_empty():
    """原文与 ai 完全相同 → 无 hunk。"""
    hunks = compute_section_diff("same text", "same text")
    assert hunks == []


def test_compute_diff_replace_hunk_has_inline():
    """单段替换 → 一个 replace hunk，带 inline diff。"""
    hunks = compute_section_diff("hello world", "hello earth")
    assert len(hunks) == 1
    h = hunks[0]
    assert h.type == "replace"
    assert h.original_para == "hello world"
    assert h.modified_para == "hello earth"
    assert h.inline is not None
    # inline 至少含一个操作，且 op 取值在 -1/0/1
    ops = {pair[0] for pair in h.inline}
    assert ops <= {-1, 0, 1}
    # 重新拼接应还原两端
    removed = "".join(t for op, t in h.inline if op <= 0)
    inserted = "".join(t for op, t in h.inline if op >= 0)
    assert removed == "hello world"
    assert inserted == "hello earth"


def test_compute_diff_insert_hunk_for_added_paragraph():
    """新增段落 → insert hunk。"""
    hunks = compute_section_diff("line1", "line1\nline2")
    types = [h.type for h in hunks]
    assert "insert" in types
    insert_hunks = [h for h in hunks if h.type == "insert"]
    assert any(h.text == "line2" for h in insert_hunks)


def test_compute_diff_delete_hunk_for_removed_paragraph():
    """删除段落 → delete hunk。"""
    hunks = compute_section_diff("line1\nline2", "line1")
    types = [h.type for h in hunks]
    assert "delete" in types
    delete_hunks = [h for h in hunks if h.type == "delete"]
    assert any(h.original_para == "line2" for h in delete_hunks)


def test_compute_diff_multiple_hunks_mixed():
    """多段变更 → 多个 hunk，且 id 唯一。"""
    original = "alpha\nbeta\ngamma"
    ai = "alpha\nBETA\ngamma\ndelta"
    hunks = compute_section_diff(original, ai)
    # 至少一个 replace（beta→BETA）和一个 insert（delta）
    types = {h.type for h in hunks}
    assert "replace" in types
    assert "insert" in types
    ids = [h.id for h in hunks]
    assert len(ids) == len(set(ids))  # id 唯一


def test_hunk_id_is_stable_and_8_chars():
    """相同输入 → 相同 id，长度 8。"""
    hid = _hunk_id("replace", "abc", "xyz")
    assert len(hid) == 8
    assert hid == _hunk_id("replace", "abc", "xyz")
    # 不同输入 → 不同 id
    assert hid != _hunk_id("replace", "abc", "ABC")


# ---------- merge_accepted_hunks ----------


def _all_hunk_ids(original_text: str, ai_text: str) -> set[str]:
    """辅助：算出 original→ai 的全部 hunk id。"""
    return {h.id for h in compute_section_diff(original_text, ai_text)}


def test_merge_all_accepted_returns_ai_text():
    """全接受 → 结果 == ai_text。"""
    original = "hello world"
    ai = "hello earth"
    ids = _all_hunk_ids(original, ai)
    merged = merge_accepted_hunks(original, ai, ids)
    assert merged == ai


def test_merge_none_accepted_returns_original_text():
    """全不接受 → 结果 == original_text。"""
    original = "hello world"
    ai = "hello earth"
    merged = merge_accepted_hunks(original, ai, set())
    assert merged == original


def test_merge_partial_accepted_keeps_unaccepted_original():
    """部分接受：未接受的 hunk 保留原文。"""
    original = "alpha\nbeta\ngamma"
    ai = "ALPHA\nBETA\nGAMMA"
    hunks = compute_section_diff(original, ai)
    assert len(hunks) == 3
    # 只接受第一个 hunk
    accepted = {hunks[0].id}
    merged = merge_accepted_hunks(original, ai, accepted)
    # 第一段被替换为 ai 段，其余保留原段
    parts = merged.split("\n")
    assert parts[0] == "ALPHA"
    assert parts[1] == "beta"
    assert parts[2] == "gamma"


def test_merge_insert_accepted_or_skipped():
    """插入 hunk：接受则出现，不接受则缺失。"""
    original = "line1"
    ai = "line1\nline2"
    insert_id = _all_hunk_ids(original, ai)

    accepted = merge_accepted_hunks(original, ai, insert_id)
    assert accepted == "line1\nline2"

    skipped = merge_accepted_hunks(original, ai, set())
    assert skipped == "line1"


def test_merge_delete_accepted_or_kept():
    """删除 hunk：接受则消失，不接受则保留。"""
    original = "line1\nline2"
    ai = "line1"
    delete_id = _all_hunk_ids(original, ai)

    accepted = merge_accepted_hunks(original, ai, delete_id)
    assert accepted == "line1"

    kept = merge_accepted_hunks(original, ai, set())
    assert kept == "line1\nline2"


# ---------- apply_diff_to_section（Tiptap 集成）----------


def _make_section(db_session, registered_user):
    """建项目取第一个章节（复用 test_sections 模式）。返回 (section, user)。"""
    from sqlalchemy import select

    from app.models import User
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.services.seed_service import ensure_default_template

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="diff 测试项目")
    section = list_sections(db_session, user_id=user.id, project_id=str(p.id))[0]
    return section, user


def _tiptap_para(text: str) -> dict:
    """构造一个单段落 Tiptap doc。"""
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def test_apply_diff_optimistic_lock_conflict_raises(db_session, registered_user):
    """乐观锁：expected_version 不匹配 → ConflictError，且不修改内容。"""
    from app.core.exceptions import ConflictError
    from app.services.diff_service import apply_diff_to_section

    section, user = _make_section(db_session, registered_user)
    assert section.version == 1
    section.content = _tiptap_para("original text")
    db_session.commit()

    with pytest.raises(ConflictError):
        apply_diff_to_section(
            db_session, user_id=user.id, section_id=str(section.id),
            ai_text="new text", accepted_hunk_ids=[],
            expected_version=999,
        )


def test_apply_diff_success_writes_tiptap_json_and_increments_version(db_session, registered_user):
    """成功 apply：section.content 变为 Tiptap JSON，version +1。"""
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    from app.services.diff_service import apply_diff_to_section

    section, user = _make_section(db_session, registered_user)
    assert section.version == 1
    original_tiptap = _tiptap_para("original text")
    section.content = original_tiptap
    db_session.commit()

    # 计算原段→ai 的 hunk id，全接受
    ai_text = "modified text"
    hunks = compute_section_diff("original text", ai_text)
    assert len(hunks) == 1
    accepted = [hunks[0].id]

    updated = apply_diff_to_section(
        db_session, user_id=user.id, section_id=str(section.id),
        ai_text=ai_text, accepted_hunk_ids=accepted,
        expected_version=1,
    )

    # version 自增
    assert updated.version == 2
    # content 是 Tiptap JSON dict，且不再是旧对象
    assert isinstance(updated.content, dict)
    assert updated.content != original_tiptap
    # round-trip：再跑一次 markdown_to_tiptap(modified text) 应等价
    assert updated.content == markdown_to_tiptap("modified text")


def test_apply_diff_with_no_accepted_hunks_keeps_original(db_session, registered_user):
    """不接受任何 hunk → 内容经 markdown round-trip 后仍表达原段。"""
    from app.services.diff_service import apply_diff_to_section

    section, user = _make_section(db_session, registered_user)
    section.content = _tiptap_para("original text")
    db_session.commit()

    updated = apply_diff_to_section(
        db_session, user_id=user.id, section_id=str(section.id),
        ai_text="totally different text", accepted_hunk_ids=[],
        expected_version=1,
    )

    assert updated.version == 2
    # 从 Tiptap JSON 提取文本，应仍是原文
    text_nodes = [
        n.get("text", "")
        for n in updated.content.get("content", [])
        for n in n.get("content", [])
    ]
    assert "original text" in "".join(text_nodes)


# ---------- compute_rewrite_diff（选区重写整章 diff，spec §3.4）----------


def test_compute_rewrite_diff_basic(db_session, registered_user):
    """选中'涉及'→AI 输出'归属于'，返回 1 个 replace hunk。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    # 给章节写入含'涉及'的内容
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "涉及", "归属于")
    assert len(hunks) == 1
    h = hunks[0]
    assert h.type == "replace"
    assert "涉及" in (h.original_para or "")
    assert "归属于" in (h.modified_para or "")


def test_compute_rewrite_diff_not_found_raises(db_session, registered_user):
    """selected_text 不在章节里 → ValidationError。"""
    from app.core.exceptions import ValidationError
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    with pytest.raises(ValidationError):
        compute_rewrite_diff(section, "不存在的文字", "新内容")


def test_compute_rewrite_diff_first_occurrence_only(db_session, registered_user):
    """选中文字多次出现，只替换首次（验证 find 而非 replaceAll）。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    # '所述' 出现两次
    section.content = _tiptap_para("所述装置包括所述凸轮")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "所述", "该")
    # 只替换首次：'该装置包括所述凸轮' vs '所述装置包括所述凸轮'
    # diff 应只产生 1 个 replace hunk（首次'所述'→'该'），第二次'所述'保留
    assert len(hunks) == 1
    assert hunks[0].type == "replace"


def test_compute_rewrite_diff_empty_section(db_session, registered_user):
    """section.content 为 None → original=''，selected_text 找不到 → ValidationError。"""
    from app.core.exceptions import ValidationError
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = None
    db_session.commit()

    with pytest.raises(ValidationError):
        compute_rewrite_diff(section, "任意文字", "新内容")


def test_compute_rewrite_diff_identical_ai_no_hunks(db_session, registered_user):
    """AI 输出与选中文字相同 → 拼接后整章无变化 → 空 hunks。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "涉及", "涉及")  # 相同
    assert hunks == []
