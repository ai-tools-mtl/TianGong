# apps/api/app/skills/zip_import.py
"""Skill zip 导入：解析 Agent Skills spec 标准的 zip 包。

支持两种布局：
- 扁平：zip 直接含 SKILL.md + scripts/ + references/ + assets/（本系统导出格式）
- 包一层目录：zip/<name>/SKILL.md（Claude/agentskills.io 标准目录格式）

安全：路径穿越防护（zip slip）、YAML frontmatter 解析、name 合规校验。
"""
import io
import re
import zipfile
from dataclasses import dataclass, field

import yaml

from app.core.exceptions import ValidationError

# spec name 规则（与 schemas/skill.py 的 _NAME_RE 一致）
_NAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,64}(?<!-)$")

# 文本脚本扩展名（→ scripts 桶）
_SCRIPT_EXTS = {".py", ".sh", ".js", ".ts", ".mjs", ".cjs"}
# 文本文档扩展名（→ references 桶）
_REFERENCE_EXTS = {".md", ".txt", ".rst"}

# 噪声目录（macOS/Windows 打包残留 + VCS）
_IGNORED_TOP_DIRS = {".git", "__MACOSX", ".DS_Store", "node_modules", "__pycache__"}


@dataclass
class ParsedSkill:
    """zip 解析结果，结构对齐 create_skill 的参数。"""
    name: str
    description: str
    body: str
    scripts: dict[str, str] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)


def _is_path_safe(member: str) -> bool:
    """拒绝路径穿越（zip slip）：绝对路径、..、Windows 盘符。"""
    if not member:
        return False
    # 绝对路径（Unix / Windows）
    if member.startswith("/") or member.startswith("\\"):
        return False
    # Windows 盘符
    if len(member) >= 2 and member[1] == ":":
        return False
    # 任何段含 ..
    parts = member.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        return False
    return True


def _strip_outer_dir(members: list[str]) -> tuple[str, str]:
    """判断是否包了一层目录，返回 (前缀, 相对路径映射函数)。

    若所有文件都在同一个顶层目录下（如 some-dir/SKILL.md），剥离该目录。
    否则视为扁平布局（前缀为空）。
    """
    # 过滤掉目录条目（以 / 结尾）和噪声
    real_files = [
        m for m in members
        if not m.endswith("/") and not m.split("/")[0] in _IGNORED_TOP_DIRS
    ]
    if not real_files:
        return "", lambda p: p

    # 取所有顶层目录名
    top_dirs = {m.split("/")[0] for m in real_files if "/" in m}
    # 也可能有顶层文件（扁平）
    top_files = {m for m in real_files if "/" not in m}

    # 若有顶层文件（如直接 SKILL.md）→ 扁平布局
    if top_files:
        return "", lambda p: p

    # 所有文件都在唯一一个顶层目录下 → 剥离它
    if len(top_dirs) == 1:
        prefix = next(iter(top_dirs))
        # 跳过噪声目录名
        if prefix in _IGNORED_TOP_DIRS:
            return "", lambda p: p
        return prefix + "/", lambda p: p[len(prefix) + 1:] if p.startswith(prefix + "/") else p

    # 多个顶层目录 → 扁平（不剥离）
    return "", lambda p: p


def _parse_frontmatter(skill_md_content: str) -> tuple[str, str, str]:
    """解析 SKILL.md：返回 (name, description, body)。

    frontmatter 是 YAML（--- 包围）。提取 name/description（必填），
    忽略 license/version 等额外字段。
    """
    content = skill_md_content
    if not content.startswith("---"):
        raise ValidationError("SKILL.md 缺少 YAML frontmatter（必须以 --- 开头）")

    # 分割 frontmatter 和 body
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValidationError("SKILL.md frontmatter 格式错误（缺少闭合 ---）")

    fm_text = parts[1]
    body = parts[2].lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        raise ValidationError(f"SKILL.md frontmatter YAML 解析失败：{e}") from e

    if not isinstance(fm, dict):
        raise ValidationError("SKILL.md frontmatter 必须是键值对")

    name = fm.get("name")
    description = fm.get("description")

    if not name:
        raise ValidationError("SKILL.md frontmatter 缺少 name 字段")
    if not description:
        raise ValidationError("SKILL.md frontmatter 缺少 description 字段")

    return str(name), str(description), body


def _validate_name(name: str) -> str:
    """校验 name 合规（spec: [a-z0-9-] 1-64，不首尾/连续连字符）。"""
    if not _NAME_RE.match(name):
        raise ValidationError(
            f"name「{name}」不合规：必须为 [a-z0-9-]，1-64 字符，不首尾/连续连字符"
        )
    if "--" in name:
        raise ValidationError(f"name「{name}」不能有连续连字符")
    return name


def _classify_file(rel_path: str, data: bytes) -> tuple[str, str | bytes]:
    """把文件分类到 scripts/references/assets 桶。

    Returns:
        (桶名, 值) —— scripts/references 返回 str（utf-8 解码），
        assets 返回 bytes。
    """
    # 按目录前缀优先
    lower = rel_path.lower()
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""

    if ext in _SCRIPT_EXTS:
        return "scripts", data.decode("utf-8", errors="replace")
    if ext in _REFERENCE_EXTS:
        return "references", data.decode("utf-8", errors="replace")
    # 其余 → assets（二进制）
    return "assets", data


def parse_skill_zip(zip_bytes: bytes) -> ParsedSkill:
    """解析 skill zip 包，返回 ParsedSkill。

    失败抛 ValidationError（缺 SKILL.md、路径穿越、frontmatter 缺字段、name 不合规）。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValidationError(f"不是有效的 zip 文件：{e}") from e

    members = zf.namelist()

    # 1. 路径穿越防护
    for m in members:
        if not _is_path_safe(m):
            raise ValidationError(f"zip 含不安全路径（路径穿越）：{m}")

    # 2. 判断布局 + 剥离外层目录
    _, rel = _strip_outer_dir(members)

    # 3. 找 SKILL.md（相对路径）
    skill_md_rel = None
    for m in members:
        if m.endswith("/"):
            continue  # 跳过目录条目
        # 跳过噪声目录
        top = m.split("/")[0]
        if top in _IGNORED_TOP_DIRS:
            continue
        if rel(m) == "SKILL.md":
            skill_md_rel = m
            break

    if skill_md_rel is None:
        raise ValidationError("zip 包缺少 SKILL.md（必须在根目录或唯一顶层目录下）")

    # 4. 解析 frontmatter
    skill_md_content = zf.read(skill_md_rel).decode("utf-8")
    name, description, body = _parse_frontmatter(skill_md_content)
    name = _validate_name(name)

    # 5. 分类其余文件
    parsed = ParsedSkill(name=name, description=description, body=body)
    for m in members:
        if m.endswith("/") or m == skill_md_rel:
            continue
        top = m.split("/")[0]
        if top in _IGNORED_TOP_DIRS:
            continue
        rp = rel(m)
        if not rp or rp == "SKILL.md":
            continue
        data = zf.read(m)
        bucket, value = _classify_file(rp, data)
        # 文件名取相对路径的 basename（扁平化，去掉中间目录）
        fname = rp.rsplit("/", 1)[-1]
        if bucket == "scripts":
            parsed.scripts[fname] = value  # type: ignore[assignment]
        elif bucket == "references":
            parsed.references[fname] = value  # type: ignore[assignment]
        else:
            parsed.assets[fname] = value  # type: ignore[assignment]

    return parsed
