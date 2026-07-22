"""解析 Word 自动编号。

Word 的自动编号（1. / 1.1 / 1.1.1）是渲染时计算的，document.xml 只存
numId 引用。本模块尽力解析 numbering.xml，并提供正则兜底（手敲编号）。

详见设计文档 9.6 与 GOTCHAS（python-docx 编号限制）。
"""

import re

# 正则：匹配 "1.1" / "1.1.2" / "2、" / "1." 等开头的编号
# 编号主体是数字串（可含点），后面可跟 . 、 或空格作为分隔
_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.、\s]")

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_numbering_from_text(text: str) -> str | None:
    """正则兜底：从段落文本提取手敲的编号。"""
    if not text:
        return None
    m = _NUMBER_RE.match(text.strip())
    return m.group(1) if m else None


class NumberingResolver:
    """解析 numbering.xml 的自动编号。

    对于 MVP，优先保证不报错（无 numbering.xml 或解析失败时优雅降级）。
    完整的计数器逻辑较复杂，此处实现基础版 + 正则兜底。
    """

    def __init__(self, numbering_part_element):
        """numbering_part_element: doc.part.numbering_part.element（lxml），可为 None。"""
        self._element = numbering_part_element
        self._abstract_nums: dict[str, dict] = {}
        self._num_to_abstract: dict[str, str] = {}
        self._counters: dict[tuple, int] = {}
        if self._element is not None:
            self._parse_numbering_xml()

    def _parse_numbering_xml(self):
        """解析 numbering.xml 的 abstractNum 定义与 num 映射。"""
        # num -> abstractNum 映射
        for num in self._element.findall(f"{{{_W_NS}}}num"):
            num_id = num.get(f"{{{_W_NS}}}numId")
            abs_ref = num.find(f"{{{_W_NS}}}abstractNumId")
            if abs_ref is not None:
                self._num_to_abstract[num_id] = abs_ref.get(f"{{{_W_NS}}}val")
        # abstractNum 各级定义
        for abs_num in self._element.findall(f"{{{_W_NS}}}abstractNum"):
            abs_id = abs_num.get(f"{{{_W_NS}}}abstractNumId")
            levels = {}
            for lvl in abs_num.findall(f"{{{_W_NS}}}lvl"):
                ilvl = lvl.get(f"{{{_W_NS}}}ilvl")
                lvl_text = lvl.find(f"{{{_W_NS}}}lvlText")
                num_fmt = lvl.find(f"{{{_W_NS}}}numFmt")
                start = lvl.find(f"{{{_W_NS}}}start")
                levels[ilvl] = {
                    "lvlText": lvl_text.get(f"{{{_W_NS}}}val") if lvl_text is not None else None,
                    "numFmt": num_fmt.get(f"{{{_W_NS}}}val") if num_fmt is not None else None,
                    "start": int(start.get(f"{{{_W_NS}}}val")) if start is not None else 1,
                }
            self._abstract_nums[abs_id] = levels

    def resolve_for_paragraph(self, paragraph) -> str | None:
        """尝试解析某段落的自动编号。无编号信息时返回 None（降级到正则）。"""
        if paragraph is None:
            return None
        try:
            pPr = paragraph._element.find(f"{{{_W_NS}}}pPr")
            if pPr is None:
                return None
            numPr = pPr.find(f"{{{_W_NS}}}numPr")
            if numPr is None:
                return None
            num_id_el = numPr.find(f"{{{_W_NS}}}numId")
            ilvl_el = numPr.find(f"{{{_W_NS}}}ilvl")
            if num_id_el is None:
                return None
            num_id = num_id_el.get(f"{{{_W_NS}}}val")
            ilvl = ilvl_el.get(f"{{{_W_NS}}}val") if ilvl_el is not None else "0"
            abs_id = self._num_to_abstract.get(num_id)
            if abs_id is None or abs_id not in self._abstract_nums:
                return None
            levels = self._abstract_nums[abs_id]
            if ilvl not in levels:
                return None
            # 自增计数器
            counter_key = (num_id, ilvl)
            self._counters[counter_key] = (
                self._counters.get(counter_key, levels[ilvl]["start"] - 1) + 1
            )
            # 上级递增时重置所有更深层级的计数器（Word 行为：
            # 1.1 → 1.2 → 2.1，不能是 1.1 → 1.2 → 2.3）
            int_ilvl = int(ilvl)
            for i in range(int_ilvl + 1, 10):  # 最多 9 级
                deeper_key = (num_id, str(i))
                if deeper_key in self._counters:
                    start_val = levels.get(str(i), {}).get("start", 1)
                    self._counters[deeper_key] = start_val - 1  # 下次 resolve 时 +1 → start
            
            count = self._counters[counter_key]
            lvl_text = levels[ilvl]["lvlText"] or ""
            # 替换所有级别的占位符（%1, %2, ...），而非仅当前级别
            # Word 多级编号 lvlText 如 "%1.%2" —— 需替换 %1 和 %2 为各自计数器的值
            result = lvl_text
            for i in range(int(ilvl) + 1):
                placeholder = f"%{i + 1}"
                ck = (num_id, str(i))
                val = self._counters.get(ck, levels.get(str(i), {}).get("start", 1))
                result = result.replace(placeholder, str(val))
            return result
        except Exception:
            return None
