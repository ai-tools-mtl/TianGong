"""专利附图 drawio XML 生成 prompt。

约束 LLM 输出纯 <mxfile> XML，供 drawio 渲染容器导出 PNG。
提炼自 drawio-skill 的 XML 生成知识（references/xml-authoring.md），针对无人值守
一次性生成场景收紧：只输出 XML、无解释文本、用确定性的手写坐标（不依赖 Graphviz）。

配色/字体/渲染参数由风格预设驱动（figure_presets.STYLE_PRESETS），patent-bw（专利黑白）
为默认，符合中国专利局《专利审查指南》正式申请标准。
"""
import re

from app.ai.figure_presets import (
    _color_block, _example_xml, get_preset,
)

# 支持的图类型（前端下拉选项对齐）。None 表示通用/让模型自行判断。
DIAGRAM_TYPES = {
    "flowchart": "流程图",
    "architecture": "系统架构图",
    "sequence": "时序图",
    "block": "模块框图",
    "state": "状态图",
    "general": "通用示意图",
}


def build_figure_prompt(user_prompt: str, diagram_type: str | None, style: str | None = None) -> str:
    """构造 LLM 的 user message。配色/字体/约束随 style 预设切换。"""
    preset = get_preset(style)
    type_hint = ""
    if diagram_type and diagram_type in DIAGRAM_TYPES:
        type_hint = f"\n图类型：{DIAGRAM_TYPES[diagram_type]}（diagram_type={diagram_type}）"

    color_section = _color_block(preset["colors"])
    example = _example_xml(preset["colors"])
    font_hint = f"所有文字 fontColor=#000000;fontFamily={preset['font_family']};fontSize={preset['font_size']};"
    extra = preset.get("extra_constraints", "")

    return f"""请为以下需求绘制一张专利交底书附图。

用户需求：{user_prompt}{type_hint}
风格预设：{preset['label']}

## 输出要求（极其重要）
- **只输出 <mxfile>...</mxfile> 的 drawio XML，禁止任何解释、说明、markdown 代码围栏。**
- 第一行必须是 `<?xml version="1.0" encoding="UTF-8"?>`，第二行必须是 `<mxfile`，最后一行必须是 `</mxfile>`。
- 不要输出 ```xml 等围栏，不要在 XML 前后加任何文字。

## drawio XML 骨架（必须遵守）
```xml
<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="drawio" version="26.0.0">
  <diagram name="专利附图">
    <mxGraphModel>
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- 用户形状从 id="2" 开始递增 -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

## 硬性规则
1. `id="0"` 和 `id="1"` 是必需的根 cell，不可省略、不可复用。
2. 用户形状 id 从 `"2"` 起递增（"2","3","4"...），所有形状 `parent="1"`。
3. 每个形状用 `<mxGeometry x y width height as="geometry" />` 给出明确坐标，自上而下、自左而右布局。
4. **【防文字超框·最重要】形状的 width/height 必须按标签文字长度计算，确保文字完整装在框内**：
   - 单字宽度 ≈ fontSize + 2 = {preset['font_size'] + 2}px（中文宋体）。标签 N 个字单行所需宽度 ≈ N × {preset['font_size'] + 2} + 16（左右 padding）。
   - **框 width 必须 ≥ 标签单行所需宽度**。若标签较长（>7 字），优先**加宽框**（width = 字数 × {preset['font_size'] + 2} + 16），不要让文字溢出。
   - 若标签确实太长（>12 字），用 `&#xa;` 拆成 2 行，同时**加大框 height**（每行 +{preset['font_size'] + 6}px）。例如标签 14 字 → 拆 2 行各 7 字，width ≈ 7 × {preset['font_size'] + 2} + 16，height ≈ {preset['font_size'] * 2 + 24}。
   - 框最小尺寸：矩形/圆角矩形 width ≥ 100、height ≥ 50；椭圆 width ≥ 100、height ≥ 60；菱形 width ≥ 120、height ≥ 80（菱形内空间小，标签要短，≤6 字）。
   - 连线标签也要短（≤4 字），长标签会盖住连线。
5. **每个连线（edge）的 mxCell 必须包含子元素 `<mxGeometry relative="1" as="geometry" />`**，否则不渲染。禁止自闭合的 edge cell。
6. 所有文字 style 里加 `html=1;whiteSpace=wrap;` 以正确换行（配合规则 4 的尺寸）。
7. 多行文字用 `&#xa;`（不是字面 \\n）。
8. 连线 style 用 `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth={preset['line_width']};` 实现智能避让路由。
9. {font_hint}

{color_section}

## 专利附图特有规范
- 每个关键部件配清晰中文标注；如涉及步骤，用「步骤 S1」「步骤 S2」等编号。
- 连线方向用箭头明确表达数据/控制流向，关键连线加文字标签说明关系（如「传输」「触发」）。
- 布局避免连线交叉：按层（自上而下或自左而右）组织，节点间距至少 40px。
- 附图整体宽度控制在 1600px 以内、高度 2000px 以内（导出清晰且不过大）。
{extra}

## 示例（两张节点 + 一条连线的最小图，仅示范结构与配色）
{example}

现在请输出附图的 drawio XML（仅 XML，无任何其它内容）。"""


_XML_FENCE_RE = re.compile(r"^\s*```(?:xml)?\s*\n|\n\s*```\s*$", re.MULTILINE)


def extract_xml(raw: str) -> str:
    """从 LLM 响应中提取 drawio XML。

    LLM 偶尔不顾指令带上 markdown 代码围栏或前后空白，统一清洗：
    - 去除 ```xml / ``` 围栏
    - 截取首个 <?xml 到最后一个 </mxfile> 之间的内容
    """
    text = _XML_FENCE_RE.sub("", raw).strip()
    # 兜底：若仍夹带多余文字，按 XML 标记截取
    start = text.find("<?xml")
    if start == -1:
        start = text.find("<mxfile")
    end = text.rfind("</mxfile>")
    if start != -1 and end != -1:
        text = text[start:end + len("</mxfile>")]
    return text.strip()
