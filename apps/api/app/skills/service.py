# apps/api/app/skills/service.py
"""Skill 业务逻辑：目录管理（本文件）+ 可见性合并（visibility.py）+ CRUD（Task 16 补）。

目录管理：把 frontmatter + 正文拼成 SKILL.md 存 MinIO，管理 scripts/references/assets。
"""
from app.core import storage as _storage_mod
from app.core.exceptions import NotFoundError

SKILL_MD_FILENAME = "SKILL.md"


def assemble_skill_md(*, name: str, description: str, body: str) -> str:
    """组装完整 SKILL.md = frontmatter + 正文。

    description 必须单行（spec 触发条件约束），调用方负责校验。
    """
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


def _key(prefix: str, filename: str) -> str:
    return f"{prefix}{filename}"


def write_skill_directory(
    *, bucket: str, prefix: str, name: str, description: str, body: str,
    scripts: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
    assets: dict[str, bytes] | None = None,
) -> None:
    """写一个完整 skill 目录到 MinIO。"""
    st = _storage_mod.get_storage()
    # SKILL.md
    st.put(
        bucket, _key(prefix, SKILL_MD_FILENAME),
        assemble_skill_md(name=name, description=description, body=body).encode("utf-8"),
        "text/markdown",
    )
    # scripts/
    for fname, code in (scripts or {}).items():
        st.put(bucket, _key(prefix, f"scripts/{fname}"), code.encode("utf-8"), "text/plain")
    # references/
    for fname, text in (references or {}).items():
        st.put(bucket, _key(prefix, f"references/{fname}"), text.encode("utf-8"), "text/plain")
    # assets/（二进制）
    for fname, data in (assets or {}).items():
        st.put(bucket, _key(prefix, f"assets/{fname}"), data, "application/octet-stream")


def read_skill_md(*, bucket: str, prefix: str) -> str:
    """读 SKILL.md 正文。不存在抛 NotFoundError。"""
    st = _storage_mod.get_storage()
    key = _key(prefix, SKILL_MD_FILENAME)
    if not st.stat(bucket, key):
        raise NotFoundError(f"Skill 不存在：{prefix}")
    return st.get(bucket, key).decode("utf-8")


def delete_skill_directory(*, bucket: str, prefix: str) -> None:
    """删 skill 目录：清空该 prefix 下所有对象（幂等）。"""
    st = _storage_mod.get_storage()
    client = st._client  # noqa: SLF001（复用已建连的 client，Storage Protocol 无 list 方法）
    real_bucket = st._resolve(bucket)  # noqa: SLF001
    objs = list(client.list_objects(real_bucket, prefix=prefix, recursive=True))
    for obj in objs:
        client.remove_object(real_bucket, obj.object_name)
