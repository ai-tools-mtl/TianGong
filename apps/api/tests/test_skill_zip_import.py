# apps/api/tests/test_skill_zip_import.py
"""Skill zip 导入核心解析测试。

用 zipfile 在内存构造测试包，不写真实文件。全 mock storage，不连 MinIO。
覆盖：扁平布局、包一层目录布局、路径穿越防护、frontmatter 解析、文件分类。
"""
import io
import zipfile

import pytest

from app.skills.zip_import import ParsedSkill, parse_skill_zip


def _make_zip(files: dict[str, bytes | str]) -> bytes:
    """构造内存 zip。files: {路径: 内容}。str 自动 utf-8 编码。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
    return buf.getvalue()


def _skill_md(name="my-skill", description="does X", body="## Steps\n1. foo",
              extra_frontmatter="") -> str:
    """构造标准 SKILL.md。extra_frontmatter 可加 license/version 等字段。"""
    fm = f"name: {name}\ndescription: {description}\n"
    if extra_frontmatter:
        fm += extra_frontmatter
    return f"---\n{fm}---\n\n{body}"


# ── 正常解析 ──


def test_parse_flat_layout():
    """扁平布局：zip 直接含 SKILL.md + scripts/references/assets。"""
    zip_bytes = _make_zip({
        "SKILL.md": _skill_md(),
        "scripts/analyze.py": "print('hi')",
        "references/note.md": "# note",
        "assets/data.bin": b"\x00\x01\x02",
    })
    parsed = parse_skill_zip(zip_bytes)
    assert parsed.name == "my-skill"
    assert parsed.description == "does X"
    assert "## Steps" in parsed.body
    assert parsed.scripts == {"analyze.py": "print('hi')"}
    assert parsed.references == {"note.md": "# note"}
    assert parsed.assets == {"data.bin": b"\x00\x01\x02"}


def test_parse_nested_layout_strips_outer_dir():
    """包一层目录布局：zip/<skill-name>/SKILL.md（外部 spec 标准格式）。

    自动剥离外层目录前缀。frontmatter name 权威（即使外层目录名不同）。
    """
    zip_bytes = _make_zip({
        "some-dir/SKILL.md": _skill_md(name="actual-name", description="d"),
        "some-dir/scripts/foo.py": "x = 1",
    })
    parsed = parse_skill_zip(zip_bytes)
    assert parsed.name == "actual-name"  # frontmatter 为准
    assert parsed.scripts == {"foo.py": "x = 1"}


def test_parse_extra_frontmatter_fields_ignored():
    """frontmatter 含 license/version 等额外字段，解析不报错（spec 允许）。"""
    zip_bytes = _make_zip({
        "SKILL.md": _skill_md(
            extra_frontmatter="license: MIT\nversion: '1.0'\n",
        ),
    })
    parsed = parse_skill_zip(zip_bytes)
    assert parsed.name == "my-skill"
    assert parsed.description == "does X"


def test_parse_minimal_zip_only_skill_md():
    """最小 zip：只有 SKILL.md，无资源目录。"""
    zip_bytes = _make_zip({"SKILL.md": _skill_md()})
    parsed = parse_skill_zip(zip_bytes)
    assert parsed.name == "my-skill"
    assert parsed.scripts == {}
    assert parsed.references == {}
    assert parsed.assets == {}


# ── 错误情况 ──


def test_missing_skill_md_raises():
    """缺 SKILL.md → ValidationError。"""
    zip_bytes = _make_zip({"scripts/foo.py": "print('x')"})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="SKILL.md"):
        parse_skill_zip(zip_bytes)


def test_missing_description_raises():
    """frontmatter 缺 description → ValidationError。"""
    zip_bytes = _make_zip({"SKILL.md": "---\nname: x\n---\n\nbody"})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="description"):
        parse_skill_zip(zip_bytes)


def test_missing_name_raises():
    """frontmatter 缺 name → ValidationError。"""
    zip_bytes = _make_zip({"SKILL.md": "---\ndescription: d\n---\n\nbody"})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="name"):
        parse_skill_zip(zip_bytes)


def test_invalid_name_uppercase_raises():
    """name 含大写 → ValidationError（spec: [a-z0-9-]）。"""
    zip_bytes = _make_zip({"SKILL.md": _skill_md(name="MySkill")})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="name"):
        parse_skill_zip(zip_bytes)


def test_invalid_name_space_raises():
    """name 含空格 → ValidationError。"""
    zip_bytes = _make_zip({"SKILL.md": _skill_md(name="my skill")})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="name"):
        parse_skill_zip(zip_bytes)


# ── 路径穿越防护（zip slip）──


def test_path_traversal_dotdot_raises():
    """zip 成员含 .. → ValidationError。"""
    zip_bytes = _make_zip({
        "../etc/passwd": "evil",
        "SKILL.md": _skill_md(),
    })
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="路径|path"):
        parse_skill_zip(zip_bytes)


def test_path_traversal_absolute_raises():
    """zip 成员是绝对路径 → ValidationError。"""
    zip_bytes = _make_zip({
        "/etc/passwd": "evil",
        "SKILL.md": _skill_md(),
    })
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="路径|path"):
        parse_skill_zip(zip_bytes)


def test_path_traversal_windows_drive_raises():
    """zip 成员含 Windows 盘符 → ValidationError。"""
    zip_bytes = _make_zip({
        "C:/windows/system32/evil.dll": b"\x00",
        "SKILL.md": _skill_md(),
    })
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="路径|path"):
        parse_skill_zip(zip_bytes)


# ── 文件分类 ──


def test_file_classification_by_extension():
    """按目录前缀 + 扩展名分类到 scripts/references/assets。"""
    zip_bytes = _make_zip({
        "SKILL.md": _skill_md(),
        "scripts/run.sh": "echo hi",
        "scripts/app.js": "console.log(1)",
        "scripts/lib.ts": "export const x = 1",
        "scripts/main.py": "print('py')",
        "references/guide.md": "# guide",
        "references/readme.txt": "text",
        "assets/image.png": b"\x89PNG",
        "assets/data.json": b'{"k":1}',  # .json 不在文本白名单 → assets
    })
    parsed = parse_skill_zip(zip_bytes)
    assert set(parsed.scripts.keys()) == {"run.sh", "app.js", "lib.ts", "main.py"}
    assert set(parsed.references.keys()) == {"guide.md", "readme.txt"}
    assert set(parsed.assets.keys()) == {"image.png", "data.json"}


def test_ignored_dirs():
    """.git/__MACOSX 等噪声目录被忽略。"""
    zip_bytes = _make_zip({
        "SKILL.md": _skill_md(),
        ".git/config": "[core]",
        "__MACOSX/._SKILL.md": b"\x00\x05\x16",
        "scripts/real.py": "print('real')",
    })
    parsed = parse_skill_zip(zip_bytes)
    assert parsed.scripts == {"real.py": "print('real')"}
    # .git / __MACOSX 不在任何桶里
    assert ".git" not in str(parsed.scripts) and ".git" not in str(parsed.assets)


def test_empty_zip_raises():
    """空 zip → ValidationError（缺 SKILL.md）。"""
    zip_bytes = _make_zip({})
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        parse_skill_zip(zip_bytes)


def test_invalid_zip_raises():
    """非 zip 内容 → 异常。"""
    from app.core.exceptions import ValidationError
    with pytest.raises((ValidationError, zipfile.BadZipFile, Exception)):
        parse_skill_zip(b"not a zip file at all")
