"""doctor：天工部署环境一键体检（借鉴机制批次 E，源自 DeerFlow make doctor 形态）。

用法（在 apps/api 下）：
    uv run python -m scripts.doctor            # 文本报告
    uv run python -m scripts.doctor --json     # JSON 输出（供部署文档回写）

检查项与失效语义分级（关键设计：报告要说清「谁挂了、挂了要不要紧」）：
- postgres 可达 + alembic 版本一致      【硬】挂了全站不可用
- minio bucket 读写探针                【硬】附件/知识库/附图链路不可用
- drawio /health                       【fail-closed】挂了则附图生成整体 503
- NLI /health                          【fail-open】挂了仅降级 neutral 合并不误删
- 全局 chat 配置可解析                  【软】未配置时用户侧报「未配置 LLM」
- 磁盘剩余 / Postgres 库大小           【信息】

退出码口径：任何【硬】失败或 drawio 挂 → 1；NLI 挂不算（可继续运行）。
所有网络探测带 TIANGONG_TESTING 跳过守卫（本地 docker 未起时不让脚本卡死，
老规矩——init_checkpointer 教训）。
"""
from __future__ import annotations

import argparse
import dataclasses
import json as jsonlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# TIANGONG_TESTING 守卫（老规矩）：测试环境默认只打印提示不探测网络
TESTING_ENV = "TIANGONG_TESTING"

# 路径：<repo>/apps/api/scripts → alembic.ini / versions 同级定位
SCRIPT_DIR = Path(__file__).resolve().parent
API_DIR = SCRIPT_DIR.parent

HARD = "硬依赖"
FAIL_CLOSED = "软依赖·fail-closed"
FAIL_OPEN = "软依赖·fail-open"
INFO = "信息"


@dataclass
class CheckResult:
    name: str
    hardness: str          # HARD / FAIL_CLOSED / FAIL_OPEN / INFO
    ok: bool
    detail: str
    hint: str = ""         # 失败时的处置建议


def decide_exit(results: list[CheckResult]) -> int:
    """退出码纯函数：【硬】失败或 drawio(fail-closed) 挂 → 1；其余 → 0。"""
    for r in results:
        if r.ok:
            continue
        if r.hardness == HARD:
            return 1
        if r.hardness == FAIL_CLOSED and r.name.startswith("drawio"):
            return 1
    return 0


def probe_postgres(database_url: str) -> CheckResult:
    """SELECT 1 + alembic_version 与 versions 目录 head 比对。"""
    try:
        from sqlalchemy import create_engine, inspect, text

        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # 迁移一致性：轻量读 alembic_version 表，与 ScriptDirectory 推出的 head 对比
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "alembic"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        db_ver = None
        insp = inspect(engine)
        if insp.has_table("alembic_version"):
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
                db_ver = row[0] if row else None
        if head is None:
            return CheckResult("postgres", HARD, True, "可达（无迁移记录，库可能未初始化）")
        if db_ver != head:
            return CheckResult(
                "postgres", HARD, False,
                f"可达但迁移落后：DB={db_ver} head={head}",
                "运行 uv run alembic upgrade head",
            )
        return CheckResult("postgres", HARD, True, f"可达且迁移一致（{db_ver}）")
    except Exception as e:  # noqa: BLE001 — 体检程序必须自己兜住一切
        return CheckResult("postgres", HARD, False, f"不可达/出错：{e}",
                           "确认 docker compose up -d postgres 与 DATABASE_URL")


def probe_minio(endpoint: str, access_key: str, secret_key: str,
                secure: bool, bucket_personal: str) -> CheckResult:
    """bucket 存在 + 小对象写删探针（附件链路的最小真实路径）。"""
    from io import BytesIO

    try:
        from minio import Minio

        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        if not client.bucket_exists(bucket_personal):
            return CheckResult("minio", HARD, False,
                               f"bucket {bucket_personal} 不存在",
                               "存储服务会自动建桶——确认 endpoint/凭据后重启 api")
        key = "_doctor_probe.txt"
        client.put_object(bucket_personal, key, BytesIO(b"ok"), length=2)
        client.remove_object(bucket_personal, key)
        return CheckResult("minio", HARD, True, f"bucket {bucket_personal} 写删探针通过")
    except Exception as e:  # noqa: BLE001
        return CheckResult("minio", HARD, False, f"不可达/读写失败：{e}",
                           "确认 docker compose up -d minio 与 MINIO_* 配置")


def _http_health(name: str, url: str, timeout: float = 5.0) -> tuple[bool, str]:
    import httpx

    resp = httpx.get(url, timeout=timeout)
    return resp.status_code == 200, f"HTTP {resp.status_code}"


def probe_drawio(base_url: str) -> CheckResult:
    try:
        ok, detail = _http_health("drawio", f"{base_url}/health")
        return CheckResult(
            "drawio 渲染微服务", FAIL_CLOSED, ok, detail,
            "" if ok else "该服务 fail-closed：挂着则附图生成整体报 503（渲染链路不可用）",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            "drawio 渲染微服务", FAIL_CLOSED, False, str(e),
            "该服务 fail-closed：挂着则附图生成整体报 503。启动 apps/drawio-render/"
            "（镜像较重，首次拉取 Chromium ~500MB+）",
        )


def probe_nli(base_url: str) -> CheckResult:
    try:
        ok, detail = _http_health("nli", f"{base_url}/health")
        return CheckResult(
            "NLI 记忆矛盾判断", FAIL_OPEN, ok, detail,
            "" if ok else "该服务 fail-open：挂着仅降级 neutral 走合并不误删，可继续运行",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            "NLI 记忆矛盾判断", FAIL_OPEN, False, str(e),
            "该服务 fail-open：挂着不影响主流程，仅记忆去重能力降级",
        )


def probe_llm_config(engine) -> CheckResult:
    """全局 chat 配置能否解析出非空 model（软）。"""
    try:
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            from app.services.llm_config_service import resolve_chat_config
            cfg = resolve_chat_config(session, user_id=None)
        if cfg is None or not getattr(cfg, "model", None):
            return CheckResult("全局 chat 配置", INFO, False, "未解析到可用配置",
                               "admin 在 /admin/console/llm 配置全局 Key，或用户自配")
        return CheckResult("全局 chat 配置", INFO, True,
                           f"model={cfg.model} source={cfg.source}")
    except Exception as e:  # noqa: BLE001
        return CheckResult("全局 chat 配置", INFO, False, f"解析异常：{e}")


def probe_disk(engine) -> CheckResult:
    """当前盘剩余空间 + Postgres 库大小（信息）。"""
    total, _used, free = shutil.disk_usage(os.getcwd())
    lines = [f"磁盘剩余 {free / 1024**3:.1f} GB（共 {total / 1024**3:.0f} GB）"]
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            size = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
            if size is not None:
                lines.append(f"Postgres 库 {size / 1024**2:.0f} MB")
    except Exception:  # noqa: BLE001 — SQLite/信息项失败静默
        pass
    warn = "" if free > 5 * 1024**3 else "⚠️ 剩余 <5GB，注意备份与日志膨胀"
    return CheckResult("磁盘/容量", INFO, True, "；".join(lines), warn)


def render_text(results: list[CheckResult], skipped: bool) -> str:
    icon = {True: "✓", False: "✗"}
    lines = ["== 天工环境体检 =="]
    if skipped:
        lines.append("(TIANGONG_TESTING=1：跳过全部网络探测)")
    for r in results:
        lines.append(f"{icon[r.ok]} [{r.hardness}] {r.name}: {r.detail}")
        if r.hint and not r.ok:
            lines.append(f"    ↳ {r.hint}")
    code = decide_exit(results)
    verdict = "环境就绪" if code == 0 else "存在问题（见上）"
    lines.append(f"== 结论：{verdict}（exit={code}）==")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="天工部署环境体检")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    from app.core.config import get_settings

    s = get_settings()
    skipped = bool(os.environ.get(TESTING_ENV))
    results: list[CheckResult] = []

    from sqlalchemy import create_engine

    engine = create_engine(s.database_url, pool_pre_ping=True)

    if not skipped:
        results.append(probe_postgres(s.database_url))
        results.append(probe_minio(
            s.minio_endpoint, s.minio_access_key, s.minio_secret_key,
            s.minio_secure, s.minio_bucket_personal))
        results.append(probe_drawio(s.drawio_base_url))
        results.append(probe_nli(s.nli_base_url))
    else:
        results.extend([
            CheckResult("postgres/minio/drawio/NLI", INFO, True, "TIANGONG_TESTING 跳过网络探测"),
        ])
    results.append(probe_llm_config(create_engine(s.database_url)))
    results.append(probe_disk(create_engine(s.database_url)))

    if args.json:
        print(jsonlib.dumps({
            "skipped_network_probes": skipped,
            "exit_code": decide_exit(results),
            "checks": [dataclasses.asdict(r) for r in results],
        }, ensure_ascii=False, indent=2))
    else:
        print(render_text(results, skipped))
    return decide_exit(results)


if __name__ == "__main__":
    sys.exit(main())
