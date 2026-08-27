"""审查服务：确定性评估管线（设计 6.3）。

load → score（Rubric 驱动 + 自一致性）→ aggregate → persist
"""

import json
import time
import uuid as uuid_mod

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from openai import BadRequestError
from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.ai.llm_errors import friendly_llm_error
from app.ai.rubric_prompts import SCORE_SYSTEM_PROMPT, build_score_prompt
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Project, ReviewLock, ReviewRecord, Section
from app.services.llm_config_service import ResolvedChatConfig, resolve_chat_config
from app.services.rubric_service import get_effective_rubric

CONSISTENCY_RUNS = 2  # 自一致性：每维度评分次数（旧 consistency_check skill 已删除，默认开启）

# ── 审查进行中互斥（dogfood 2026-08-19：审查是分钟级同步长任务，离开页面
# 重进既看不到进行中状态、又能再点一次 → 并发两轮浪费 LLM 调用 + 同轮次重复落库）。
# DB 行标记（review_locks 表，2026-08-25 升级）：原进程内 dict 在多 worker 部署下
# 各进程各一份互不可见 → 并发双跑；现改为 INSERT 占坑 + 条件 UPDATE 抢占 stale 锁，
# 原子性由数据库保证（PG 行锁 / SQLite 写串行），跨进程可靠。
# stale 阈值按「距上次进度」计（评分循环每次 LLM 调用完成都续期 last_touch）：
# 长但仍在推进的审查（如 LLM 慢、文档长）不会误判失效导致并发双跑；超阈值
# 无进展视为挂死进程的残留锁，自动失效放行重试。started_at 只在占坑时写入、
# 心跳不动它——/review/status 的 started_at 与 409 的「已进行 X 分钟」须是真实起点。
# 注意：锁的写操作（占坑/心跳/释放）直接 commit 调用方 session——审查评分循环
# 期间 session 无未落库写入，commit 只是结束当前读事务，无副作用。
_RUNNING_STALE_SECONDS = 900


def _try_acquire_review_lock(db: Session, project_id) -> tuple[float | None, str | None]:
    """占坑。成功返回 (None, owner_token)；冲突返回 (对方 started_at, None)。

    三段式：① INSERT 空坑（无锁时最快路径）；② 撞主键 → 条件 UPDATE 抢占
    stale 锁（WHERE last_touch < 阈值，rowcount==1 才算抢到——并发抢占由数据库
    串行化，只有一方成功）；③ 抢不到 → 读当前持有者 started_at 返回（409 文案用）。
    极小窗口：②的 UPDATE 执行前 holder 恰好释放（行没了）→ 回到 ① 重试。
    """
    token = str(uuid_mod.uuid4())
    now = time.time()
    while True:
        db.add(ReviewLock(project_id=project_id, owner_token=token,
                          started_at=now, last_touch=now))
        try:
            db.commit()
            return None, token
        except IntegrityError:
            db.rollback()
        res = db.execute(
            sa_update(ReviewLock)
            .where(
                ReviewLock.project_id == project_id,
                ReviewLock.last_touch < now - _RUNNING_STALE_SECONDS,
            )
            .values(owner_token=token, started_at=now, last_touch=now)
        )
        db.commit()
        if res.rowcount == 1:
            return None, token
        row = db.get(ReviewLock, project_id)
        if row is not None:
            return row.started_at, None


def _touch_review_lock(db: Session, project_id, owner_token: str) -> None:
    """心跳续期：刷新 last_touch（stale 窗口从最后进度起算），不改 started_at。

    只作用于自己占的坑（owner_token 匹配）：锁被抢占后，原僵死进程的迟到
    心跳不能把新持有者的锁续活。
    """
    db.execute(
        sa_update(ReviewLock)
        .where(ReviewLock.project_id == project_id,
               ReviewLock.owner_token == owner_token)
        .values(last_touch=time.time())
    )
    db.commit()


def _release_review_lock(db: Session, project_id, owner_token: str) -> None:
    """释放锁（owner_token 匹配才删——僵死进程恢复后不能误删新持有者的锁）。"""
    db.execute(
        sa_delete(ReviewLock)
        .where(ReviewLock.project_id == project_id,
               ReviewLock.owner_token == owner_token)
    )
    db.commit()


def is_review_running(db: Session, project_id) -> float | None:
    """查询进行中状态：在跑返回真实 started_at(epoch)（stale 按 last_touch 判定），否则 None。"""
    row = db.get(ReviewLock, project_id)
    if row is not None and time.time() - row.last_touch < _RUNNING_STALE_SECONDS:
        return row.started_at
    return None


def run_review(db: Session, *, user_id, project_id: str) -> ReviewRecord:
    """执行完整审查。"""
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    # 同项目审查互斥：进行中再次触发 → 409（防并发双跑浪费 LLM 调用 + 同轮次重复落库）
    conflict_started, token = _try_acquire_review_lock(db, pid)
    if conflict_started is not None:
        waited = int(time.time() - conflict_started)
        raise ConflictError(f"审查正在进行中（已进行约 {waited // 60} 分钟），请等待完成后再试")
    try:
        return _run_review_locked(
            db, user_id=user_id, project=project, pid=pid, lock_token=token
        )
    finally:
        # rollback 丢弃执行途中的残留状态（如 persist 失败留下的半截记录/失败事务），
        # 保证紧随其后的锁释放 commit 不连带写入这些数据
        db.rollback()
        _release_review_lock(db, pid, token)


def _run_review_locked(
    db: Session, *, user_id, project: Project, pid, lock_token: str
) -> ReviewRecord:
    """run_review 的实际执行体（调用前须已持有项目审查锁，lock_token 用于心跳续期）。"""

    # 旧 project-scoped skill 开关已删除（spec Q5 解耦）。
    # rubric_review / consistency_check 默认全开；后续按 spec 用全局/用户级 Skill 重建（Task 6+）。
    runs = CONSISTENCY_RUNS

    # ① load
    rubric = get_effective_rubric(db, user_id=user_id)
    sections = _get_section_texts(db, pid)
    last_review = _get_last_review(db, pid)

    # 阶段 0：解析生效 LLM 配置（断链修复：审查调用真驱动 LLM）。无配置直接拒绝。
    llm_config = resolve_chat_config(db, user_id=user_id)
    if llm_config is None:
        raise ValidationError("未配置 LLM，无法执行审查")

    # ② score（Rubric 驱动 + 自一致性）
    # 失败治理（dogfood 2026-08-19）：LLM 全挂（如余额不足 429/1113）时旧版静默吞异常，
    # 落库一份全 50 分「评分失败」废报告、前端 toast「审查完成」——用户完全看不到真实原因。
    # 现在：单 run 失败记 warning 降级兜底；全部 run 失败则拒绝落库、抛友好错误。
    dimension_scores = []
    total_runs = 0
    failed_runs = 0
    last_exc: Exception | None = None
    for criterion in rubric.criteria:
        scores = []
        last_evidence = ""
        last_suggestion = ""
        for _ in range(runs):
            total_runs += 1
            try:
                score, evidence, suggestion = _score_dimension(criterion, sections, llm_config)
            except Exception as e:  # noqa: BLE001 — 降级点：单 run 失败不阻断，全失败在下方统一报错
                failed_runs += 1
                last_exc = e
                logger.warning(
                    "审查评分调用失败 dimension={} error={}", criterion.get("key"), e
                )
                score, evidence, suggestion = 50, "评分失败", "请重试"
            scores.append(score)
            last_evidence = evidence
            last_suggestion = suggestion
            _touch_review_lock(db, pid, lock_token)  # 每次评分调用完成即进度，续期 stale 窗口
        avg_score = sum(scores) / len(scores)
        dimension_scores.append({
            "key": criterion["key"],
            "name": criterion["name"],
            "weight": criterion["weight"],
            "score": round(avg_score),
            "run_scores": scores,
            "evidence": last_evidence,
            "suggestion": last_suggestion,
        })

    # 全部评分调用失败 → 几乎必为 LLM 配置/账户级故障（余额不足、key 失效等），
    # 此时报告没有任何信息量，拒绝落库，把真实原因（友好映射后）抛给用户。
    if total_runs > 0 and failed_runs == total_runs:
        raise ValidationError(friendly_llm_error(last_exc))

    # ③ aggregate
    total = sum(d["score"] * d["weight"] for d in dimension_scores)
    resolved, remaining = _compare_issues(dimension_scores, last_review)

    # ③b 跨章节一致性检查（全篇质量报告新增，+1 次 LLM 调用）
    # T2 spec §3.2.1：传 title→key 映射，产出 location_section_keys 结构化定位
    title_key_map = {
        s.title: s.key for s in db.scalars(
            select(Section).where(Section.project_id == pid)
        )
    }
    cross_issues = _check_cross_section_consistency(sections, llm_config, title_key_map=title_key_map)
    _touch_review_lock(db, pid, lock_token)

    # ③c 问题按章节定位聚合（把 dimension 的 evidence/suggestion 归到对应章节）
    section_issues = _aggregate_section_issues(db, pid, dimension_scores)

    # ④ persist
    record = ReviewRecord(
        project_id=pid,
        user_id=user_id,
        rubric_snapshot=rubric.criteria,
        round=(last_review.round + 1) if last_review else 1,
        total_score=round(total),
        previous_score=last_review.total_score if last_review else None,
        dimension_scores=dimension_scores,
        resolved_issues=resolved,
        remaining_issues=remaining,
        cross_section_issues=cross_issues,
        section_issues=section_issues,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _get_section_texts(db: Session, project_id) -> dict[str, str]:
    from app.services.summary_service import _extract_text
    sections = list(db.scalars(
        select(Section).where(Section.project_id == project_id).order_by(Section.order)
    ))
    return {s.title: _extract_text(s.content) if s.content else "" for s in sections}


def _get_last_review(db: Session, project_id) -> ReviewRecord | None:
    return db.scalar(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project_id)
        .order_by(ReviewRecord.created_at.desc())
    )


def _score_dimension(
    criterion: dict, sections: dict[str, str], llm_config: ResolvedChatConfig
) -> tuple[int, str, str]:
    """单维度评分。

    [S5] 优先用 with_structured_output(DimensionScore) 强约束输出（替掉脆弱正则）。
    provider 不支持原生 structured output 时（NotImplementedError/AttributeError，
    D1 决策兼容国产 provider），fallback 到普通 invoke + _parse_json_response。
    失败时抛出原始异常——降级策略由调用方（run_review）统一决定：
    部分 run 失败兜底 50 分，全部失败拒绝落库并报友好错误。
    """
    llm = get_llm(llm_config)
    prompt = build_score_prompt(criterion, sections)
    messages = [
        SystemMessage(content=SCORE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    # 路径 A：结构化输出（首选）。支持 provider 会返回 DimensionScore 实例。
    # 结构化不支持的两类信号都走路径 B：
    # - NotImplementedError/AttributeError：本地 langchain 链不支持（D1 国产 provider 兼容）
    # - BadRequestError：服务端拒绝 response_format（DeepSeek「This response_format
    #   type is unavailable now」实测 400，2026-08-19 dogfood——普通 invoke 是通的）
    from app.ai.schemas.review_schema import DimensionScore
    try:
        structured_llm = llm.with_structured_output(DimensionScore)
        result = structured_llm.invoke(messages)
        # result 是 DimensionScore 实例（结构化输出）；也可能退化为 dict（兜底）
        if isinstance(result, DimensionScore):
            return (result.score, result.evidence, result.suggestion)
        data = result  # dict 形态
    except (NotImplementedError, AttributeError, BadRequestError):
        # 路径 B：退回普通 invoke + 括号配平解析
        resp = llm.invoke(messages)
        data = _parse_json_response(resp.content)

    # 批次 F schema 校验（「验证世界而非自我汇报」）：字段缺失/类型错/越界一律
    # 抛错计入该 run 失败——绝不静默取默认分（旧 `data.get("score", 50)` 会把
    # 解析失败伪装成 50 分混入生产评分与基线）。
    return _validate_dimension_payload(data)


def _validate_dimension_payload(data: object) -> tuple[int, str, str]:
    """校验单维度评分载荷：score 数值且 0-100、evidence/suggestion 字段存在。

    严格优于宽容：调用方（run_review / review_baseline）已有失败计数与兜底路径，
    这里放宽只会把垃圾数据洗白成 50 分。
    """
    if not isinstance(data, dict):
        raise ValueError(f"评分载荷非 dict：{type(data).__name__}")
    missing = [k for k in ("score", "evidence", "suggestion") if k not in data]
    if missing:
        raise ValueError(f"评分载荷缺字段：{missing}")
    raw = data["score"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"score 非数值：{raw!r}")
    score = int(raw)
    if not 0 <= score <= 100:
        raise ValueError(f"score 越界：{score}")
    return score, str(data["evidence"]), str(data["suggestion"])


def _parse_json_response(text: str) -> dict:
    """[S5] 从 LLM 文本响应中提取并解析 JSON。

    [S5] 健壮化：旧正则排除花括号，遇到 dict 嵌 dict（如 evidence 含嵌套对象）
    会在内层 } 处截断，解析失败。改用括号配平算法提取最外层完整 JSON 对象，
    支持任意深度嵌套。
    """
    if not isinstance(text, str):
        text = str(text)
    # 找第一个 {，用括号配平找到对应的 }（支持嵌套）
    start = text.find("{")
    if start == -1:
        return json.loads(text)  # 无花括号，直接解析（可能本身是合法 JSON）
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    # 未找到配平的 }，尝试整体解析
    return json.loads(text)


def _compare_issues(
    dimension_scores: list[dict], last_review: ReviewRecord | None
) -> tuple[list, list]:
    if not last_review:
        return [], [d["suggestion"] for d in dimension_scores if d.get("suggestion")]
    resolved = []
    remaining = []
    last_map = {d["key"]: d for d in last_review.dimension_scores}
    for d in dimension_scores:
        old = last_map.get(d["key"])
        if old and d["score"] > old["score"]:
            resolved.append(f"{d['name']} 提升（{old['score']}→{d['score']}）")
        if d.get("suggestion"):
            remaining.append(d["suggestion"])
    return resolved, remaining


def _check_cross_section_consistency(
    sections: dict[str, str], llm_config: ResolvedChatConfig,
    title_key_map: dict[str, str] | None = None,
) -> list[dict]:
    """跨章节一致性检查（+1 次 LLM 调用，结构化输出）。

    检测术语统一性、权利要求-实施例对应、三段论呼应、逻辑矛盾。
    失败时降级返回空列表（不阻断审查主流程）。

    title_key_map（T2 spec §3.2.1）：{章节标题: 章节 key}。给出时：
    - prompt 附 key 清单，要求 LLM 输出 location_section_keys 从清单取值；
    - 后处理兜底（单点化，前端不做二次匹配，D14）：过滤清单外的幻觉 key；
      keys 为空时按 location_sections 标题精确匹配回填。None 时行为同旧版。
    """
    from app.ai.review_prompts import CONSISTENCY_SYSTEM_PROMPT, build_consistency_prompt
    from app.ai.schemas.review_schema import ConsistencyReport

    llm = get_llm(llm_config)
    prompt = build_consistency_prompt(sections, title_key_map=title_key_map)
    messages = [
        SystemMessage(content=CONSISTENCY_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    def _normalize(issue: dict) -> dict:
        """按 CrossSectionIssue 契约补齐缺省字段。

        文本 fallback / dict 兜底路径没有 Pydantic 校验，LLM 漏字段时
        issue 缺 key（实测 location_sections 缺失 → 前端 .length 崩溃，
        2026-08-19 dogfood）。单点规范化，前端不做二次防御（D14）。
        """
        return {
            "type": issue.get("type") or "other",
            "description": issue.get("description") or "",
            "location_sections": issue.get("location_sections") or [],
            "suggestion": issue.get("suggestion") or "",
            "location_section_keys": issue.get("location_section_keys") or [],
        }

    def _postprocess(issues: list[dict]) -> list[dict]:
        issues = [_normalize(i) for i in issues]
        if not title_key_map:
            return issues
        valid_keys = set(title_key_map.values())
        for issue in issues:
            keys = [k for k in (issue.get("location_section_keys") or []) if k in valid_keys]
            if not keys:
                # LLM 未给/全被过滤：按标题精确匹配回填（无匹配留空——前端仅展示）
                keys = [
                    title_key_map[t] for t in (issue.get("location_sections") or [])
                    if t in title_key_map
                ]
            issue["location_section_keys"] = keys
        return issues

    try:
        structured_llm = llm.with_structured_output(ConsistencyReport)
        result = structured_llm.invoke(messages)
        if isinstance(result, ConsistencyReport):
            return _postprocess([issue.model_dump() for issue in result.issues])
        # dict 兜底
        return _postprocess(result.get("issues", []))
    except (NotImplementedError, AttributeError, BadRequestError):
        # provider 不支持 structured output（本地或服务端 400 拒绝 response_format），
        # 退回普通 invoke + 文本解析（与 _score_dimension 路径 B 同策略）
        try:
            resp = llm.invoke(messages)
            data = _parse_json_response(resp.content)
            return _postprocess(data.get("issues", []))
        except Exception as e:
            logger.warning("跨章节一致性检查失败（降级为空，不阻断审查）: {}", e)
            return []
    except Exception as e:
        logger.warning("跨章节一致性检查失败（降级为空，不阻断审查）: {}", e)
        return []


def _aggregate_section_issues(
    db: Session, project_id, dimension_scores: list[dict]
) -> list[dict]:
    """把维度评分的 evidence/suggestion 按章节聚合。

    遍历所有章节，把 dimension 的 evidence/suggestion 中提及该章节标题的问题归到对应章节。
    章节无问题的跳过（不产生空条目）。
    返回 [{section_key, section_title, issues: [str]}]。
    """
    sections = list(db.scalars(
        select(Section).where(Section.project_id == project_id).order_by(Section.order)
    ))

    result = []
    for s in sections:
        issues = []
        for d in dimension_scores:
            # evidence/suggestion 中提及章节标题的归入该章节
            combined = f"{d.get('evidence', '')} {d.get('suggestion', '')}"
            if s.title in combined:
                issue_text = f"【{d['name']}】{d.get('suggestion', '') or d.get('evidence', '')}"
                issues.append(issue_text)
        if issues:
            result.append({
                "section_key": s.key,
                "section_title": s.title,
                "issues": issues,
            })
    return result
