"""[S5] 审查评分结构化输出 schema（spec 2026-07-29-prompt-content-design §4 S5）。

供 review_service._score_dimension 用 with_structured_output(DimensionScore) 强约束
LLM 输出，替掉脆弱的正则 JSON 解析（旧正则连嵌套 JSON 都解析不了）。

字段含义：
- score：该维度得分，0-100 整数（schema 层 ge/le 约束，超范围直接 ValidationError）
- evidence：评分依据，要求引用交底书具体内容
- suggestion：可操作的改进建议，无改进空间时填「已达标」
"""
from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    """单个审查维度的结构化评分输出。"""

    score: int = Field(ge=0, le=100, description="该维度得分，0-100 整数")
    evidence: str = Field(description="评分依据，需引用交底书具体内容")
    suggestion: str = Field(description="可操作的改进建议，无改进空间时填『已达标』")


class CrossSectionIssue(BaseModel):
    """跨章节一致性问题的结构化输出。"""

    type: str = Field(description="问题类型：terminology（术语不一致）/reference（引用错位）/contradiction（逻辑矛盾）/other")
    description: str = Field(description="问题描述，需具体")
    location_sections: list[str] = Field(description="涉及哪些章节标题")
    suggestion: str = Field(description="修复建议")
    # T2 spec §3.2.1：结构化定位（章节 key，供前端路由到章节发起修订）。
    # 旧数据无此字段（默认空，向后兼容）；LLM 未给时由后端按标题兜底回填。
    location_section_keys: list[str] = Field(
        default_factory=list,
        description="涉及章节的 key（从用户消息给出的 key 清单中取值，不要编造）",
    )


class ConsistencyReport(BaseModel):
    """跨章节一致性检查报告（结构化输出）。"""

    issues: list[CrossSectionIssue] = Field(
        default_factory=list,
        description="检测到的跨章节问题列表，无问题时为空",
    )
