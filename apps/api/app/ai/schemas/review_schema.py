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
