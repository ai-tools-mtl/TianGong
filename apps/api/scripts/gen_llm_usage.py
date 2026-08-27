"""docs 目录自动生成器：LLM 调用点目录 + SystemSetting 键目录（借鉴机制批次 B/B+）。

可再生成就 regenerate 而不是 reject（原则出自 deepseek-harness 文档纪律）：
调用点 / 配置键的「存在性清单」由本脚本从源码 AST 生成，CI 用 --check 校验新鲜度——
新增或移动调用点而忘记重跑生成，PR 直接红灯。叙述性内容（触发场景、降级策略）
仍然人工维护，脚本绝不触碰定界符之外的章节。

用法（在 apps/api 下）：
    uv run python -m scripts.gen_llm_usage            # 重新生成全部目标
    uv run python -m scripts.gen_llm_usage --check    # CI 新鲜度校验（不一致 exit 1）

生成物（含 do-not-edit 头与定界符）：
  - docs/llm-usage.md 中 <!-- BEGIN AUTO ... --> 区块（插入既有手写文档）
  - docs/system-settings-catalog.md 整文件（纯生成物）
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# ── 路径定位（<repo>/apps/api/scripts/gen_llm_usage.py → 仓库根）────────────
# parent 链：[0]=apps/api/scripts 的上一级……确切地：
#   Path(__file__).resolve().parent == <repo>/apps/api/scripts
#   其 parents: [0]=<repo>/apps/api, [1]=<repo>/apps, [2]=<repo>
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
APP_DIR = REPO_ROOT / "apps" / "api" / "app"
DOCS_DIR = REPO_ROOT / "docs"

LLM_USAGE_DOC = DOCS_DIR / "llm-usage.md"
SETTINGS_CATALOG_DOC = DOCS_DIR / "system-settings-catalog.md"

BEGIN_MARK = "<!-- BEGIN AUTO: llm-call-sites（机器生成，勿手改；改完代码后运行 python -m scripts.gen_llm_usage） -->"
END_MARK = "<!-- END AUTO: llm-call-sites -->"

RESOLVERS = {
    "resolve_chat_config": "chat 强模型",
    "resolve_lite_config": "轻量模型",
    "resolve_embedding_config": "embedding",
}


@dataclass(frozen=True)
class CallSite:
    rel_path: str   # 相对 apps/api 的 posix 路径
    line: int
    scope: str      # 所属函数/方法限定名，模块级为 "<module>"
    resolver: str


@dataclass(frozen=True)
class SettingKey:
    key: str
    rel_path: str
    line: int


def _iter_app_sources(root: Path):
    for p in sorted(root.rglob("*.py")):
        yield p


def _scope_of(stack: list[ast.AST]) -> str:
    """由祖先节点栈推导所属函数限定名（Class.func / Module）。"""
    parts: list[str] = []
    for node in stack:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(node.name)
        elif isinstance(node, ast.ClassDef):
            parts.append(node.name)
    # 栈序为外→内，限定名直接外→内拼接即为正确 qualname（Service.method）
    return ".".join(parts) if parts else "<module>"


def find_resolver_call_sites(root: Path = APP_DIR, *, rel_base: Path = REPO_ROOT) -> list[CallSite]:
    """AST 扫描 root 下所有 resolve_*_config 调用点。

    匹配规则：Call(func) 为 Name 或 Attribute 时取「最终名字」，命中 RESOLVERS 集合。
    支持直接 import、as 别名（别名以 import 映射回真名）、模块属性访问三种形态。
    rel_base：产物中路径的相对基准（生产=仓库根；测试注入临时根以便离线构造）。
    """
    sites: list[CallSite] = []
    for path in _iter_app_sources(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        alias_map: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name in RESOLVERS:
                        alias_map[a.asname or a.name] = a.name
        # 带父栈遍历（ast.walk 丢失层级，自实现递归）
        def visit(node: ast.AST, stack: list[ast.AST]) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack = [*stack, node]
            if isinstance(node, ast.Call):
                target: str | None = None
                if isinstance(node.func, ast.Name):
                    raw = node.func.id
                    target = alias_map.get(raw, raw)
                elif isinstance(node.func, ast.Attribute):
                    target = node.func.attr
                if target in RESOLVERS:
                    sites.append(CallSite(
                        rel_path=path.relative_to(rel_base).as_posix(),
                        line=node.lineno,
                        scope=_scope_of(stack),
                        resolver=target,
                    ))
            for child in ast.iter_child_nodes(node):
                visit(child, stack)
        visit(tree, [])
    return sorted(sites, key=lambda s: (s.rel_path, s.line))


def find_setting_keys(root: Path = APP_DIR, *, rel_base: Path = REPO_ROOT) -> list[SettingKey]:
    """收集 SystemSetting 键：`*_KEY = "<字面量>"` 常量赋值 + SystemSetting(key="<字面量>") 字面量。"""
    keys: dict[str, SettingKey] = {}
    for path in _iter_app_sources(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # 形态一：服务模块的 <NAME>_KEY = "..." 常量定义
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name) and t.id.endswith("_KEY") and node.value:
                    v = node.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value:
                        keys.setdefault(v.value, SettingKey(
                            key=v.value,
                            rel_path=path.relative_to(rel_base).as_posix(),
                            line=node.lineno,
                        ))
            # 形态二：SystemSetting(key="...") 内联字面量
            if isinstance(node, ast.Call):
                f = node.func
                fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                if fname == "SystemSetting":
                    for kw in node.keywords:
                        if kw.arg == "key" and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str) and kw.value.value:
                            keys.setdefault(kw.value.value, SettingKey(
                                key=kw.value.value,
                                rel_path=path.relative_to(rel_base).as_posix(),
                                line=kw.value.lineno,
                            ))
    return [keys[k] for k in sorted(keys)]


def render_llm_auto_block(sites: list[CallSite]) -> str:
    counts = {r: sum(1 for s in sites if s.resolver == r) for r in RESOLVERS}
    lines = [
        f"共 {len(sites)} 个调用点"
        f"（chat {counts['resolve_chat_config']} / lite {counts['resolve_lite_config']}"
        f" / embedding {counts['resolve_embedding_config']}）。"
        "下表由 `python -m scripts.gen_llm_usage` 从源码 AST 生成，只管「存在性」——",
        "各调用的触发场景与降级策略见上文人工维护章节。",
        "",
        "| 调用点 | 所在函数 | 解析器 |",
        "|---|---|---|",
    ]
    for s in sites:
        lines.append(
            f"| `{s.rel_path}:{s.line}` | `{s.scope}` | {RESOLVERS[s.resolver]} (`{s.resolver}`) |"
        )
    return "\n".join(lines)


def upsert_auto_region(doc_text: str, inner: str) -> str:
    """把生成内容写入定界符之间；无定界符时追加到文首引言之后。"""
    block = f"{BEGIN_MARK}\n{inner}\n{END_MARK}"
    if BEGIN_MARK in doc_text and END_MARK in doc_text:
        pre, rest = doc_text.split(BEGIN_MARK, 1)
        _, post = rest.split(END_MARK, 1)
        return f"{pre}{block}{post}"
    return f"{doc_text.rstrip()}\n\n{block}\n"


def render_settings_doc(keys: list[SettingKey]) -> str:
    lines = [
        "# SystemSetting 键目录",
        "",
        "> **机器生成，勿手编。** 来源：`apps/api/app` 下全部 `_KEY = \"...\"` 常量与"
        "`SystemSetting(key=\"...\")` 内联字面量。",
        "> 重新生成：`cd apps/api && uv run python -m scripts.gen_llm_usage`；"
        "CI 以 --check 模式校验新鲜度。",
        "",
        f"共 {len(keys)} 个键。",
        "",
        "| 键名 | 定义位置 |",
        "|---|---|",
    ]
    for k in keys:
        lines.append(f"| `{k.key}` | `{k.rel_path}:{k.line}` |")
    return "\n".join(lines) + "\n"


def _check(name: str, actual: str, expected: str) -> bool:
    if actual == expected:
        print(f"[ok] {name} 新鲜")
        return True
    print(
        f"[stale] {name} 与源码不一致。\n"
        f"  修复：cd apps/api && uv run python -m scripts.gen_llm_usage 后提交产物。",
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅校验新鲜度，不写文件")
    args = parser.parse_args(argv)

    ok = True

    # 目标一：llm-usage.md 自动区块
    sites = find_resolver_call_sites()
    llm_doc = LLM_USAGE_DOC.read_text(encoding="utf-8")
    new_llm = upsert_auto_region(llm_doc, render_llm_auto_block(sites))
    if args.check:
        ok &= _check("docs/llm-usage.md 自动区块", new_llm, llm_doc)
    else:
        if new_llm != llm_doc:
            LLM_USAGE_DOC.write_text(new_llm, encoding="utf-8", newline="\n")
            print(f"[gen] docs/llm-usage.md 已更新（{len(sites)} 个调用点）")

    # 目标二：SystemSetting 键目录（整文件生成物）
    keys = find_setting_keys()
    settings_doc = SETTINGS_CATALOG_DOC.read_text(encoding="utf-8") \
        if SETTINGS_CATALOG_DOC.exists() else ""
    expected_settings = render_settings_doc(keys)
    if args.check:
        ok &= _check("docs/system-settings-catalog.md", expected_settings, settings_doc)
    else:
        if expected_settings != settings_doc:
            SETTINGS_CATALOG_DOC.write_text(expected_settings, encoding="utf-8", newline="\n")
            print(f"[gen] docs/system-settings-catalog.md 已更新（{len(keys)} 个键）")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
