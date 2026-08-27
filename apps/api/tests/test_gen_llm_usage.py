"""gen_llm_usage 生成器单测（批次 B）：AST 扫描规则与幂等渲染。

扫描函数接受注入的 root——测试在 tmp_path 造迷你源码树，不触碰真实 app/ 目录。
"""
from pathlib import Path

from scripts.gen_llm_usage import (
    BEGIN_MARK,
    END_MARK,
    CallSite,
    find_resolver_call_sites,
    find_setting_keys,
    render_llm_auto_block,
    upsert_auto_region,
)


def _make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "app"
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return root


class TestResolverCallSites:
    def test_direct_call_and_attribute_call(self, tmp_path):
        root = _make_tree(tmp_path, {
            "svc.py": (
                "from app.services.llm_config_service import resolve_chat_config\n"
                "\n"
                "def use(db):\n"
                "    cfg = resolve_chat_config(db, user_id=1)\n"
                "    cfg2 = mod.resolve_lite_config(db)\n"
            ),
        })
        sites = find_resolver_call_sites(root, rel_base=root)
        assert [(s.resolver, s.scope) for s in sites] == [
            ("resolve_chat_config", "use"),
            ("resolve_lite_config", "use"),
        ]
        assert sites[0].rel_path.endswith("svc.py")

    def test_alias_import_resolved_to_canonical(self, tmp_path):
        root = _make_tree(tmp_path, {
            "alias_user.py": (
                "from app.services.llm_config_service import resolve_embedding_config as emb\n"
                "\n"
                "async def build(db):\n"
                "    return await emb(db)\n"
            ),
        })
        sites = find_resolver_call_sites(root, rel_base=root)
        assert len(sites) == 1
        assert sites[0].resolver == "resolve_embedding_config"

    def test_non_matching_names_ignored_and_sorted_by_line(self, tmp_path):
        root = _make_tree(tmp_path, {
            "noise.py": (
                "def resolve_chat_config_none():\n"   # 定义同名函数不是调用
                "    pass\n"
                "\n"
                "x = resolve_unknown_config(1)          # 不在白名单\n"
                "\n"
                "def later(db):\n"
                "    resolve_lite_config(db)             # 行号应在 x 之后\n"
            ),
        })
        sites = find_resolver_call_sites(root, rel_base=root)
        assert [s.resolver for s in sites] == ["resolve_lite_config"]
        assert sites[0].scope == "later"

    def test_methods_report_class_scope(self, tmp_path):
        root = _make_tree(tmp_path, {
            "cls.py": (
                "class Svc:\n"
                "    def run(self, db):\n"
                "        return resolve_chat_config(db)\n"
            ),
        })
        assert find_resolver_call_sites(root, rel_base=root)[0].scope == "Svc.run"


class TestSettingKeys:
    def test_key_constant_and_inline_literal_both_captured_deduped(self, tmp_path):
        root = _make_tree(tmp_path, {
            "a_service.py": 'FOO_KEY = "foo_config"\n',
            "b_api.py": (
                'from app.models import SystemSetting\n'
                'db.add(SystemSetting(key="bar_flag", value={}))\n'
                '# 同键再次出现（读路径）不应产生重复行\n'
                'row = get(SystemSetting.key == "foo_config")\n'
            ),
        })
        keys = find_setting_keys(root, rel_base=root)
        names = [k.key for k in keys]
        assert names == sorted(names)              # 输出按键名排序（确定性）
        assert "foo_config" in names and "bar_flag" in names
        assert names.count("foo_config") == 1      # 常量定义优先收录一次

    def test_non_literal_or_non_key_assignments_ignored(self, tmp_path):
        root = _make_tree(tmp_path, {
            "c.py": (
                'PLAIN_NAME = "plain"\n'            # 名字不含 _KEY 后缀
                'DYNAMIC_KEY = compute()            # 含后缀但非字面量\n'
                'db.add(SystemSetting(key=user_input))  # 动态键不可静态收集\n'
            ),
        })
        assert find_setting_keys(root, rel_base=root) == []


class TestRenderAndUpsert:
    def test_render_contains_counts_table_and_no_timestamp(self):
        sites = [
            CallSite("apps/api/app/a.py", 10, "f", "resolve_chat_config"),
            CallSite("apps/api/app/b.py", 20, "g", "resolve_lite_config"),
        ]
        out = render_llm_auto_block(sites)
        assert "共 2 个调用点（chat 1 / lite 1 / embedding 0）" in out
        assert "`apps/api/app/a.py:10`" in out
        import re
        # 幂等关键：输出不含任何会随时间变化的内容（日期/时间戳）
        assert not re.search(r"\d{4}-\d{2}-\d{2}", out)

    def test_upsert_inserts_when_markers_absent_then_replaces_in_place(self):
        doc = "# 手写引言\n\n保留的人工章节"
        inner_v1 = "第一版生成内容"
        merged = upsert_auto_region(doc, inner_v1)
        assert inner_v1 in merged and BEGIN_MARK in merged and END_MARK in merged
        assert "# 手写引言" in merged and "保留的人工章节" in merged

        # 第二次生成：只替换定界符之间，人工章节原样保留
        inner_v2 = "第二版生成内容（新增了调用点）"
        merged2 = upsert_auto_region(merged, inner_v2)
        assert inner_v2 in merged2 and inner_v1 not in merged2
        assert merged2.count(BEGIN_MARK) == 1
        assert "保留的人工章节" in merged2
