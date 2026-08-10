"""专利附图风格预设定义（内置基线）。

3 个固定预设，admin 可通过 SystemSetting 微调参数（覆盖内置），不能增删。
预设驱动两件事：(1) prompt 的配色段（figure_prompts.build_figure_prompt 读取）；
(2) 渲染参数 scale/border（figure_service 读取）。

预设依据中国专利局《专利审查指南》+ 电子申请指引：
- patent-bw：纯黑白线条图，白底黑字，统一线宽，宋体——符合正式申请标准（默认）
- clean-color：清晰彩色——内部交底书用，不交专利局
- technical：灰度——技术文档风格

渲染规格（scale=3≈300DPI、border=20 白边距、统一线宽字体、图框标号）三个预设统一高规格，
因为即便彩色附图也需要清晰可印。
"""

# 预设 id → 标签（前端下拉选项）
PRESET_LABELS = {
    "patent-bw": "专利黑白（符合专利局标准）",
    "clean-color": "清晰彩色",
    "technical": "技术灰度",
}

DEFAULT_PRESET = "patent-bw"

# 内置预设基线。admin 微调（figure_preset_service）的 overrides 会逐字段覆盖这些值。
# colors 的每个 key 对应一种形状，value 是 drawio style 片段（拼进 mxCell style=）。
# 统一含 align=center;verticalAlign=middle;spacing=8：文字居中 + 内边距，防溢出贴边。
STYLE_PRESETS: dict[str, dict] = {
    "patent-bw": {
        "label": PRESET_LABELS["patent-bw"],
        # 纯黑白：白底 + 黑边框 + 统一线宽 1.5px。无任何彩色/灰度填充。
        # align/verticalAlign/spacing 防文字超框：水平+垂直居中，8px 内边距。
        "colors": {
            "rect": "fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rounded": "rounded=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "cylinder": "shape=cylinder3;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rhombus": "rhombus;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "ellipse": "ellipse;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "container": "swimlane;startSize=30;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
        },
        "font_family": "SimSun",  # 宋体（专利附图惯用）
        "font_size": 12,
        "line_width": 1.5,
        # patent-bw 专属约束（追加到 prompt）
        "extra_constraints": (
            "本图为专利局正式申请用的黑白线条图，必须严格遵守：\n"
            "- 纯黑白：所有形状白底（fillColor=#ffffff）+ 黑边框（strokeColor=#000000），"
            "禁止任何彩色或灰度填充\n"
            "- 统一线宽 1.5px（所有 strokeWidth=1.5），线条均匀清晰\n"
            "- 文字黑色（fontColor=#000000），宋体\n"
            "- 整图外加一个图框（外层 swimlane 边框，包住所有部件）\n"
            "- 关键部件用数字标号（10、20、30...），标号放在部件框内或旁边\n"
            "- 连线用实线箭头表达流向，统一黑色\n"
            "- 满足复印/扫描后仍清晰可辨（线条足够深、间距足够大）"
        ),
        "render": {"scale": 3, "border": 20},  # 300DPI + 20px 白边距
    },
    "clean-color": {
        "label": PRESET_LABELS["clean-color"],
        # 清晰彩色：drawio 默认色系，区分度高，内部交底书用
        "colors": {
            "rect": "fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rounded": "rounded=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "cylinder": "shape=cylinder3;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rhombus": "rhombus;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "ellipse": "ellipse;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "container": "swimlane;startSize=30;fillColor=#f5f5f5;strokeColor=#666666;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
        },
        "font_family": "Microsoft YaHei",  # 微软雅黑（屏幕清晰）
        "font_size": 12,
        "line_width": 1.5,
        "extra_constraints": "",  # 彩色无额外专利约束
        "render": {"scale": 3, "border": 20},
    },
    "technical": {
        "label": PRESET_LABELS["technical"],
        # 技术灰度：中性灰阶，专业文档风格，介于黑白与彩色之间
        "colors": {
            "rect": "fillColor=#f5f5f5;strokeColor=#333333;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rounded": "rounded=1;fillColor=#f5f5f5;strokeColor=#333333;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "cylinder": "shape=cylinder3;fillColor=#e0e0e0;strokeColor=#333333;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "rhombus": "rhombus;fillColor=#eeeeee;strokeColor=#555555;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "ellipse": "ellipse;fillColor=#e8e8e8;strokeColor=#333333;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
            "container": "swimlane;startSize=30;fillColor=#fafafa;strokeColor=#333333;strokeWidth=1.5;align=center;verticalAlign=middle;spacing=8;",
        },
        "font_family": "SimSun",
        "font_size": 12,
        "line_width": 1.5,
        "extra_constraints": "",  # 灰度无额外专利约束
        "render": {"scale": 3, "border": 20},
    },
}


def normalize_style(style: str | None) -> str:
    """规范化 style id。未知/None 兜底到 patent-bw（默认）。"""
    if not style or style not in STYLE_PRESETS:
        return DEFAULT_PRESET
    return style


def get_preset(style: str | None) -> dict:
    """取预设参数。未知/None 兜底到 patent-bw（默认）。

    返回的 dict 含规范化后的 'id' 字段（供调用方落库记录实际生效的预设）。
    """
    sid = normalize_style(style)
    preset = dict(STYLE_PRESETS[sid])  # 浅拷贝，避免改内置
    preset["id"] = sid
    return preset


def _color_block(colors: dict) -> str:
    """生成 prompt 的「形状与配色」段（由预设 colors 驱动）。"""
    return (
        "## 形状与配色（严格使用以下 style 片段，拼进每个 mxCell 的 style= 属性）\n"
        f"- 矩形（流程/模块）：`rounded=0;whiteSpace=wrap;html=1;{colors['rect']}`\n"
        f"- 圆角矩形（服务/处理）：`rounded=1;whiteSpace=wrap;html=1;{colors['rounded']}`\n"
        f"- 圆柱（数据库/存储）：`whiteSpace=wrap;html=1;{colors['cylinder']}`\n"
        f"- 菱形（判断/决策）：`whiteSpace=wrap;html=1;{colors['rhombus']}`\n"
        f"- 椭圆（开始/结束）：`whiteSpace=wrap;html=1;{colors['ellipse']}`\n"
        f"- 容器（分组/图框）：`whiteSpace=wrap;html=1;{colors['container']}` 子元素 parent=容器id、坐标相对容器"
    )


def _example_xml(colors: dict) -> str:
    """生成最小示例 XML（配色随预设，避免 LLM 照彩色示例产出彩色图）。

    示例刻意展示「文字-尺寸自适应」：短标签「客户端」用 120×60 够；
    长标签「API 请求&#xa;处理模块」拆 2 行 + 加宽加高（160×70），示范防溢出。
    """
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<mxfile host="drawio" version="26.0.0"><diagram name="示例"><mxGraphModel><root>'
        f'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<mxCell id="2" value="客户端" style="rounded=1;whiteSpace=wrap;html=1;{colors["rounded"]}" vertex="1" parent="1">'
        f'<mxGeometry x="80" y="80" width="120" height="60" as="geometry"/></mxCell>'
        # 长标签示例：拆 2 行（&#xa;），框加宽到 160、加高到 70 装下两行
        f'<mxCell id="3" value="API 请求&#xa;处理模块" style="rounded=1;whiteSpace=wrap;html=1;{colors["rounded"]}" vertex="1" parent="1">'
        f'<mxGeometry x="70" y="220" width="160" height="70" as="geometry"/></mxCell>'
        f'<mxCell id="4" value="请求" style="edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=1.5;" edge="1" parent="1" source="2" target="3">'
        f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        f'</root></mxGraphModel></diagram></mxfile>'
    )
