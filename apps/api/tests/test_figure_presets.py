"""风格预设逻辑测试：预设定义、规范化兜底、配色段生成、admin 微调合并。"""
from app.ai.figure_presets import (
    DEFAULT_PRESET, STYLE_PRESETS, _color_block, get_preset, normalize_style,
)


def test_three_presets_defined():
    """内置恰好 3 个预设。"""
    assert set(STYLE_PRESETS.keys()) == {"patent-bw", "clean-color", "technical"}


def test_normalize_style_unknown_falls_back_to_default():
    """未知/None style 兜底到 patent-bw（默认）。"""
    assert normalize_style(None) == DEFAULT_PRESET == "patent-bw"
    assert normalize_style("nonexistent") == "patent-bw"
    assert normalize_style("clean-color") == "clean-color"


def test_get_preset_returns_id_for_db_storage():
    """get_preset 返回的 dict 含规范化后的 id（供落库记录生效预设）。"""
    p = get_preset(None)
    assert p["id"] == "patent-bw"
    p2 = get_preset("technical")
    assert p2["id"] == "technical"


def test_patent_bw_is_pure_black_white():
    """patent-bw 所有颜色必须是纯黑白（白底黑边框），无彩色/灰度填充。"""
    p = get_preset("patent-bw")
    for shape, style in p["colors"].items():
        assert "#ffffff" in style, f"{shape} 非白底"
        assert "#000000" in style, f"{shape} 非黑边框"
        # 禁止彩色 hex（蓝绿黄红）
        for forbidden in ("#dae8fc", "#d5e8d4", "#fff2cc", "#f8cecc", "#6c8ebf", "#82b366"):
            assert forbidden not in style, f"{shape} 含彩色 {forbidden}"


def test_patent_bw_high_res_render():
    """patent-bw 渲染规格 scale=3（300DPI）+ border=20（白边距）。"""
    p = get_preset("patent-bw")
    assert p["render"]["scale"] == 3
    assert p["render"]["border"] == 20


def test_all_presets_high_res():
    """三个预设统一高规格（scale=3 + border=20）。"""
    for sid in STYLE_PRESETS:
        p = get_preset(sid)
        assert p["render"]["scale"] == 3, f"{sid} 不是 300DPI"
        assert p["render"]["border"] == 20, f"{sid} 无白边距"


def test_color_block_contains_preset_colors():
    """配色段由预设 colors 驱动，patent-bw 段含黑白不含彩色。"""
    p = get_preset("patent-bw")
    block = _color_block(p["colors"])
    assert "#ffffff" in block
    assert "#000000" in block
    # clean-color 段含彩色
    p2 = get_preset("clean-color")
    block2 = _color_block(p2["colors"])
    assert "#dae8fc" in block2  # 蓝


def test_build_figure_prompt_uses_style_colors():
    """build_figure_prompt 的输出随 style 切换配色。"""
    from app.ai.figure_prompts import build_figure_prompt

    bw = build_figure_prompt("测试", "flowchart", style="patent-bw")
    color = build_figure_prompt("测试", "flowchart", style="clean-color")
    # patent-bw prompt 含黑白 + 专利约束；clean-color 含蓝色
    assert "#000000" in bw
    assert "#dae8fc" not in bw  # 黑白不含蓝
    assert "#dae8fc" in color    # 彩色含蓝
    # patent-bw 有额外专利约束文字
    assert "黑白线条图" in bw or "纯黑白" in bw


def test_build_figure_prompt_unknown_style_uses_default():
    """未知 style 兜底到 patent-bw 配色。"""
    from app.ai.figure_prompts import build_figure_prompt

    out = build_figure_prompt("测试", None, style="nonexistent")
    assert "#000000" in out  # 走了 patent-bw


# ── 预设 service：admin 微调合并 ──

def test_preset_service_merge_overrides(db_session):
    """admin 微调覆盖内置默认（深合并）。"""
    from app.services import figure_preset_service

    # 未微调前：patent-bw font_size=12（内置）
    presets = figure_preset_service.get_figure_presets(db_session)
    assert presets["patent-bw"]["font_size"] == 12

    # admin 微调 font_size=14
    figure_preset_service.set_figure_preset(
        db_session, preset_id="patent-bw", overrides={"font_size": 14},
    )
    presets = figure_preset_service.get_figure_presets(db_session)
    assert presets["patent-bw"]["font_size"] == 14  # 被覆盖
    # 其它字段未被覆盖（label 仍是内置）
    assert presets["patent-bw"]["label"] == STYLE_PRESETS["patent-bw"]["label"]


def test_preset_service_rejects_non_tunable_field(db_session):
    """非白名单字段（如 colors）被忽略，不能覆盖。"""
    from app.services import figure_preset_service

    figure_preset_service.set_figure_preset(
        db_session, preset_id="clean-color",
        overrides={"colors": {"rect": "hacked"}, "font_size": 16},  # colors 不在白名单
    )
    presets = figure_preset_service.get_figure_presets(db_session)
    # colors 未被篡改（仍是内置），font_size 生效
    assert presets["clean-color"]["colors"]["rect"] == STYLE_PRESETS["clean-color"]["colors"]["rect"]
    assert presets["clean-color"]["font_size"] == 16


def test_preset_service_unknown_preset_raises(db_session):
    """微调未知预设报错。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.services import figure_preset_service

    with pytest.raises(ValidationError):
        figure_preset_service.set_figure_preset(
            db_session, preset_id="nonexistent", overrides={"font_size": 14},
        )
