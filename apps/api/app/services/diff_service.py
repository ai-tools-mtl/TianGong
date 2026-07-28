"""diff 计算与应用服务（设计 plan15 / spec §4，Tiptap 适配版）。

两级 diff：
- 段落级：difflib.SequenceMatcher 对齐段落列表，确定每段 replace/insert/delete
- 字符级：对 replace 段用 diff_match_patch 算 inline diff（前端高亮增删字符）

Hunk 携带 inline（replace 时）或整段文本（insert/delete 时）。
apply 时合并 accepted hunks → markdown→Tiptap JSON 写入 section.content。

GOTCHAS：
- diff_match_patch 包名与类名都是 diff_match_patch
- dmp.diff_main 返回 [[op, text], ...]，op: -1/0/1
- dmp.diff_cleanupSemantic 就地修改（返回 None）
- Hunk id 用 md5 前 8 位（稳定，便于前端重算后保留选中状态）
"""

import difflib
import hashlib
from dataclasses import dataclass

from diff_match_patch import diff_match_patch


@dataclass
class Hunk:
    """一个段落的变更。

    id: 8 位 hex（md5 稳定生成）
    type: "replace" | "insert" | "delete"
    inline: replace 时的字符级 diff [[op, text], ...]（op: -1 删 / 0 等 / 1 插）
    text: insert 时的整段新文本
    original_para: replace/delete 时的原段文本
    modified_para: replace 时的修改后文本
    """
    id: str
    type: str
    inline: list[list] | None = None
    text: str | None = None
    original_para: str | None = None
    modified_para: str | None = None


def _hunk_id(hunk_type: str, original: str, modified: str) -> str:
    """稳定的 hunk id：md5(type:original:modified) 前 8 位。

    相同输入 → 相同 id，前端重算 diff 后可按 id 保留 accept/reject 状态。
    """
    raw = f"{hunk_type}:{original}:{modified}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:8]


def _inline_diff(original: str, modified: str) -> list[list]:
    """字符级 inline diff（diff-match-patch 格式 [[op, text], ...]）。

    开启 diff_cleanupSemantic 合并细碎 diff，提升可读性。
    """
    dmp = diff_match_patch()
    diffs = dmp.diff_main(original, modified)
    dmp.diff_cleanupSemantic(diffs)  # 就地修改
    return [[op, text] for op, text in diffs]


def compute_section_diff(original_text: str, ai_text: str) -> list[Hunk]:
    """计算段落级 + 字符级 diff，返回 Hunk 列表。

    流程：
    1. 按换行切分段落（保留空行参与对齐）
    2. difflib.SequenceMatcher 对齐 original / ai 段落列表
    3. 对每个非 equal 块生成 hunk(s)：
       - replace 块：逐段对（同索引位置的 o段↔a段）生成 replace hunk（带 inline diff）；
         若 o/a 段数不等，多出的段降级为 insert/delete。
       - insert 块：每段一个 insert hunk
       - delete 块：每段一个 delete hunk
    """
    orig_paras = original_text.split("\n") if original_text else []
    ai_paras = ai_text.split("\n") if ai_text else []

    matcher = difflib.SequenceMatcher(a=orig_paras, b=ai_paras, autojunk=False)
    hunks: list[Hunk] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        o_block = orig_paras[i1:i2]
        a_block = ai_paras[j1:j2]

        if tag == "replace":
            # 逐段对生成 replace hunk；多出的段降级为 insert/delete
            common = min(len(o_block), len(a_block))
            for k in range(common):
                o_para = o_block[k]
                a_para = a_block[k]
                if o_para == a_para:
                    continue  # 相同段不算变更（SequenceMatcher 对齐后理论上不会，保险）
                hunks.append(Hunk(
                    id=_hunk_id("replace", o_para, a_para),
                    type="replace",
                    inline=_inline_diff(o_para, a_para),
                    original_para=o_para,
                    modified_para=a_para,
                ))
            # 原段多出 → delete
            for k in range(common, len(o_block)):
                o_para = o_block[k]
                hunks.append(Hunk(
                    id=_hunk_id("delete", o_para, ""),
                    type="delete",
                    original_para=o_para,
                ))
            # 新段多出 → insert
            for k in range(common, len(a_block)):
                a_para = a_block[k]
                hunks.append(Hunk(
                    id=_hunk_id("insert", "", a_para),
                    type="insert",
                    text=a_para,
                ))
        elif tag == "insert":
            for a_para in a_block:
                hunks.append(Hunk(
                    id=_hunk_id("insert", "", a_para),
                    type="insert",
                    text=a_para,
                ))
        elif tag == "delete":
            for o_para in o_block:
                hunks.append(Hunk(
                    id=_hunk_id("delete", o_para, ""),
                    type="delete",
                    original_para=o_para,
                ))

    return hunks


def merge_accepted_hunks(
    original_text: str, ai_text: str, accepted_hunk_ids: set[str],
) -> str:
    """合并被接受的 hunks，返回最终文本。

    策略：对 original → ai 的每个 hunk，若 id 在 accepted_hunk_ids 中则应用变更，
    否则保留原始内容。

    实现方式：重算 diff，按 opcodes 重建段落列表：
    - equal 块：直接取 original 段
    - replace/insert/delete 块：检查每个 hunk 的 id 是否被接受
      - 被接受 → 取 ai 段（replace 取 modified_para，insert 取 text，delete 跳过）
      - 不接受 → 取 original 段（replace 取 original_para，insert 跳过，delete 保留原段）
    """
    orig_paras = original_text.split("\n") if original_text else []
    ai_paras = ai_text.split("\n") if ai_text else []

    matcher = difflib.SequenceMatcher(a=orig_paras, b=ai_paras, autojunk=False)
    result: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        o_block = orig_paras[i1:i2]
        a_block = ai_paras[j1:j2]

        if tag == "equal":
            result.extend(o_block)
            continue

        if tag == "replace":
            common = min(len(o_block), len(a_block))
            for k in range(common):
                o_para = o_block[k]
                a_para = a_block[k]
                if o_para == a_para:
                    result.append(o_para)
                    continue
                hid = _hunk_id("replace", o_para, a_para)
                result.append(a_para if hid in accepted_hunk_ids else o_para)
            for k in range(common, len(o_block)):
                o_para = o_block[k]
                hid = _hunk_id("delete", o_para, "")
                if hid not in accepted_hunk_ids:
                    result.append(o_para)  # 不接受删除 → 保留原段
            for k in range(common, len(a_block)):
                a_para = a_block[k]
                hid = _hunk_id("insert", "", a_para)
                if hid in accepted_hunk_ids:
                    result.append(a_para)  # 接受插入 → 加新段
        elif tag == "insert":
            for a_para in a_block:
                hid = _hunk_id("insert", "", a_para)
                if hid in accepted_hunk_ids:
                    result.append(a_para)
        elif tag == "delete":
            for o_para in o_block:
                hid = _hunk_id("delete", o_para, "")
                if hid not in accepted_hunk_ids:
                    result.append(o_para)  # 不接受删除 → 保留原段

    return "\n".join(result)


# ---------- apply 到 section（DB + Tiptap 集成）----------

def apply_diff_to_section(
    db, *, user_id, section_id: str, ai_text: str,
    accepted_hunk_ids: set[str], expected_version: int,
):
    """把接受的 hunks 应用到 section 的 Tiptap 内容。

    流程（设计 plan15 / spec §4，Tiptap 版）：
    1. get_section（含权限校验 + 乐观锁）
    2. _tiptap_to_markdown(section.content) 得 original_text
    3. merge_accepted_hunks(original_text, ai_text, accepted_hunk_ids) 得 merged_text
    4. markdown_to_tiptap(merged_text) 写回 section.content
    5. section.version += 1
    6. db.commit(); db.refresh(section); return section
    """
    from app.core.exceptions import ConflictError
    from app.services.export_service import _tiptap_to_markdown
    from app.services.section_service import get_section
    from app.ai.markdown_to_tiptap import markdown_to_tiptap

    # 1. get_section + 乐观锁
    section = get_section(db, user_id=user_id, section_id=section_id)
    if expected_version != section.version:
        raise ConflictError(
            f"内容已被修改（当前版本 {section.version}，期望 {expected_version}）"
        )

    # 2. Tiptap JSON → markdown 纯文本
    original_text = _tiptap_to_markdown(section.content) if section.content else ""

    # 3. 合并接受的 hunks
    merged_text = merge_accepted_hunks(original_text, ai_text, accepted_hunk_ids)

    # 4. markdown → Tiptap JSON 写回
    section.content = markdown_to_tiptap(merged_text)

    # 5. 版本号 +1
    section.version += 1

    # 6. 提交
    db.commit()
    db.refresh(section)
    return section


def compute_rewrite_diff(section, selected_text: str, ai_text: str) -> tuple[list[Hunk], str]:
    """选区重写的整章 diff（方案 B：后端代算拼接，spec §3.4）。

    流程：
    1. _tiptap_to_markdown(section.content) → 整章原文 markdown
    2. 原文.find(selected_text) → 首次出现位置；找不到报 ValidationError
    3. 首次出现替换成 ai_text → ai_full_text（多次出现只替换首次，避免误伤）
    4. compute_section_diff(原文, ai_full_text) → hunks（复用已有函数）

    返回 (hunks, ai_full)：ai_full 是注入后的整章 markdown，apply-diff 时必须
    原样回传作为 ai_text，否则后端按 (original, ai_text) 重算的 hunks 与此处
    生成的 hunk id 不一致，accepted_hunk_ids 对不上 → 数据损坏。
    """
    from app.core.exceptions import ValidationError
    from app.services.export_service import _tiptap_to_markdown

    original = _tiptap_to_markdown(section.content) if section.content else ""
    idx = original.find(selected_text)
    if idx == -1:
        raise ValidationError("无法在章节中定位选区，请重新选择")
    ai_full = original[:idx] + ai_text + original[idx + len(selected_text):]
    return compute_section_diff(original, ai_full), ai_full
