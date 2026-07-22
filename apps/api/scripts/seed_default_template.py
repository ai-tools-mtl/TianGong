"""单独 seed 系统默认模板（薄包装）。

完整初始化（建表 + admin + 模板 + Rubric）请用：
    uv run python -m scripts.init_db

本脚本只在已建好表、只想补 seed 默认模板的场景下使用，内部直接复用
init_db._seed_system_defaults，保持单一数据源。
"""

from scripts.init_db import _seed_system_defaults


def main() -> None:
    _seed_system_defaults()


if __name__ == "__main__":
    main()
