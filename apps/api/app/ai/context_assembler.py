"""五层上下文装配（设计 5.4）。

[系统层] 角色 + 输出规范
[项目层] 已确认章节的 summary
[章节层] 当前章节的 Prompt 策略
[对话层] 本章节历史对话
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy import select

from app.ai.section_prompts import get_section_prompt
from app.models import Message, Project, Section
from app.services.summary_service import _extract_text

SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问
6. 当用户表达了值得长期记住的偏好、事实或领域约定时，调用 save_memory 工具保存。
   只记跨项目稳定的信息（如「偏好简洁风格」「我做新能源电池」），不记项目内具体决策。
7. 当撰写本章需要参考历史案例、已有交底书的写法或技术细节时，调用 rag_search 工具检索用户知识库。
   查询用技术关键词或问题描述；检索结果仅供参考，需结合本项目实际改写，勿照搬。"""


def assemble_messages(
    section: Section,
    history: list[Message],
    user_input: str | None = None,
    project_summaries: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
) -> list:
    """装配完整的消息列表。"""
    messages = []

    sp = get_section_prompt(section.key)
    system_content = SYSTEM_PROMPT + f"\n\n当前正在撰写章节：【{section.title}】\n"
    system_content += f"本章目标：{sp.goal}\n"
    # [S1] 知识资产激活：注入 guide_questions + completion_criteria
    # 此前两字段定义了却从未注入，模型不知道「什么算写完」、缺少主动追问引导。
    if sp.guide_questions:
        system_content += "引导要点（可主动追问用户，不必逐条回答）：\n"
        system_content += "\n".join(f"- {q}" for q in sp.guide_questions) + "\n"
    system_content += f"输出格式要求：{sp.output_format}\n"
    system_content += f"达标判定：{sp.completion_criteria}"
    # [S4-1] few-shot 范例（双装配一致：build_system_prompt 与 assemble_messages 同步注入）
    if sp.few_shot_example:
        system_content += f"\n参考范例（学习结构与句式，不要照抄内容）：\n{sp.few_shot_example}"

    if project_summaries:
        summary_text = "\n".join(
            f"- {s['title']}：{s['summary']}" for s in project_summaries if s.get("summary")
        )
        if summary_text:
            system_content += f"\n\n已完成章节摘要（可作为上下文参考）：\n{summary_text}"

    # 知识库层（RAG 检索注入，设计 10.4）
    if knowledge_context:
        kb_text = "\n".join(
            f"- 《{k.get('project_title', '历史案例')}》{k.get('section_key', '')}：{k['content'][:200]}"
            for k in knowledge_context
        )
        if kb_text:
            system_content += f"\n\n相关知识库参考（来自你的历史案例）：\n{kb_text}"

    messages.append(SystemMessage(content=system_content))

    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    if user_input:
        messages.append(HumanMessage(content=user_input))

    return messages


def get_project_summaries(db, project_id) -> list[dict]:
    """获取项目已确认章节的 summary（跨章节上下文）。"""
    from sqlalchemy import select

    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.status == "confirmed")
            & (Section.summary.isnot(None))
        ).order_by(Section.order)
    )
    return [{"title": s.title, "summary": s.summary} for s in sections]


# 前文注入字符软上限（T1 方案，spec §2.3 决策③）
# MVP 阶段无真实长文数据，覆盖 90% 场景；超长文场景等真实数据出现再做分块/滑动窗口
WRITTEN_SECTIONS_CHAR_BUDGET = 8000

# [S2-1] 章节状态 → 行为模式提示（让模型据状态切换策略，而非一刀切）。
# 状态后端已有（Section.status），此前没进 prompt——模型不知道白纸/草稿/定稿该用不同策略。
SECTION_STATUS_HINTS = {
    "empty": (
        "章节进度：本章还是空白。你的首要任务是【引导用户补充关键技术细节】，"
        "不要急着代写——信息不足时主动追问，而非凭空编造。"
    ),
    "drafting": (
        "章节进度：本章已有草稿。用户可能在打磨或追问，"
        "【根据用户意图决定是补充、修改还是答疑】，避免推翻已有内容。"
    ),
    "confirmed": (
        "章节进度：本章已定稿。用户若再次提问，【默认是微调或答疑，避免大改】，"
        "除非用户明确要求重写。"
    ),
}

# [S2-2] 意图 → 行为指令（让模型据用户意图切换行为，spec §4 S2-2）。
# 此前用户输入直接塞进 messages，模型不区分「代写/答疑/改写/引导」，
# 导致该代写时不停追问、该答疑时甩一整段草稿。
# 意图由 app.ai.intent.classify_intent（规则层）识别，注入此处对应指令。
# "none"（未识别）不在此表 → 不注入意图段，走默认行为（不强分类，D1 决策）。
INTENT_HINTS = {
    "draft": "用户意图：【想让你代写】。综合对话和前文章节，直接产出结构化内容，不要反复追问。",
    "edit": "用户意图：【想改某段】。先定位要改的内容，按用户指令做最小修改，保持其余不变。",
    "info": "用户意图：【在问问题】。简洁答疑，必要时举例，不要借机代写整段内容。",
    "guide": "用户意图：【想被引导】。用引导式提问帮用户厘清思路，而非直接代写。",
}


def get_written_sections_text(db, project_id, exclude_key: str) -> str:
    """查询同项目所有非空章节（不论 status，排除当前章节），提取纯文本，截断到软上限。

    - 不论 status：drafting / confirmed 都注入（绕开 summary 的 confirmed 触发限制，spec §3.1.2）
    - content.isnot(None)：空章节跳过
    - 按 Section.order 装配，超 WRITTEN_SECTIONS_CHAR_BUDGET 时截断当前章并中止（保证前面章节完整）
    - 复用 summary_service._extract_text 提取 Tiptap JSON 纯文本（与 rag/archiver、review_service 同一既定模式）
    """
    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.key != exclude_key)
            & (Section.content.isnot(None))
        ).order_by(Section.order)
    )
    parts: list[str] = []
    total = 0
    for s in sections:
        text = _extract_text(s.content).strip()
        if not text:
            continue
        chunk = f"## {s.title}\n{text}"
        if total + len(chunk) > WRITTEN_SECTIONS_CHAR_BUDGET:
            # 软上限：保留前面已装配的，当前章截断后中止
            remaining = WRITTEN_SECTIONS_CHAR_BUDGET - total
            if remaining > 20:  # 剩余空间太小（连标题+几个字都塞不下）就不塞半截
                parts.append(f"## {s.title}\n{text[:remaining]}\n…（已截断）")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


def _format_metadata(metadata: dict | None) -> str:
    """格式化项目 metadata（JSON dict）为可读文本。防御性：只取字符串/数字值，跳过嵌套结构。

    metadata 结构未定死（Project.metadata_ 是自由 JSON），做防御性格式化避免
    嵌套 dict/list 把 system prompt 搞乱。spec §3.1.3。
    """
    if not isinstance(metadata, dict) or not metadata:
        return ""
    lines = []
    for k, v in metadata.items():
        if isinstance(v, (str, int, float)):
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)


def _search_user_memories(db, user_id, query: str):
    """检索用户记忆，失败时静默返回空（不阻断 prompt 装配）。

    失败时必须 db.rollback()：PostgreSQL 下任何 SQL 失败会让事务进入
    aborted 状态，后续同一 session 的查询全被拒绝（InFailedSqlTransaction），
    进而毒化主对话流程（如取 messages 历史）。rollback 让事务恢复可用。
    """
    try:
        from app.services.memory_service import search_memories
        return search_memories(db, user_id=user_id, query=query)
    except Exception:
        logger.warning("记忆检索失败，降级返回空（不阻断 prompt 装配）", exc_info=True)
        db.rollback()
        return []


def _hot_user_memories(db, user_id, *, limit=15, exclude_ids=None):
    """[红利③配套] 热门记忆常驻视图：top-N 热度记忆，排除已检索命中的 id。

    与 _search_user_memories（按 query 语义检索）互补：常驻保证高频偏好每轮
    可见（检索只保证与当前输入相关的记忆可见）。失败降级空 + rollback（同上）。
    """
    try:
        from app.services.memory_service import list_top_hot_memories
        return list_top_hot_memories(db, user_id=user_id, limit=limit, exclude_ids=exclude_ids)
    except Exception:
        logger.warning("热门记忆读取失败，降级返回空（不阻断 prompt 装配）", exc_info=True)
        db.rollback()
        return []


def _get_profile_memories(db, user_id):
    """[S2-3] 取用户画像记忆（source=profile）。失败静默返回空（不阻断 prompt 装配）。

    画像记忆存职业/领域/专业水平（如「用户是专利代理人，机械领域」），
    用于调节模型的表达密度。与 _search_user_memories 同样需 rollback 防事务毒化。

    注意：结构化 WritingProfile（/settings/profile）优先，本函数是其 fallback——
    若用户填了 WritingProfile，build_system_prompt 会跳过此函数。
    """
    try:
        from app.services.memory_service import list_memories
        return list_memories(db, user_id=user_id, source="profile")
    except Exception:
        logger.warning("画像记忆读取失败，降级返回空", exc_info=True)
        db.rollback()
        return []


def _get_writing_profile(db, user_id):
    """读取结构化写作画像（WritingProfile 表）。失败静默返回 None（不阻断装配）。

    与 _get_profile_memories 的关系：本函数读结构化表（5 个固定字段，用户显式维护），
    _get_profile_memories 读 user_memory(source=profile) 自由记忆。
    build_system_prompt 优先用结构化画像；无则 fallback 到自由记忆。
    """
    try:
        from app.services.profile_service import get_profile
        return get_profile(db, user_id=user_id)
    except Exception:
        logger.warning("写作画像读取失败，降级返回 None", exc_info=True)
        db.rollback()
        return None


def _proficiency_density_hint(proficiency: str | None, profession: str | None) -> str:
    """据结构化画像的 proficiency/profession 返回表达密度指令。

    优先级：proficiency 显式三档 > profession 关键词推断 > 默认中间档。
    """
    from app.models.writing_profile import (
        PROFICIENCY_EXPERT, PROFICIENCY_NOVICE, PROFICIENCY_INTERMEDIATE,
    )
    # proficiency 显式档位优先
    if proficiency == PROFICIENCY_EXPERT:
        return "用户是专利领域专家，可使用高密度专利术语，无需解释基础概念。"
    if proficiency == PROFICIENCY_NOVICE:
        return "用户是技术发明人/初学者，把专利术语翻译成大白话，必要时用类比。"
    # proficiency=intermediate 或 None 时，用 profession 关键词兜底
    if profession:
        if any(kw in profession for kw in _PROFESSIONAL_KEYWORDS):
            return "用户是专利专业人士，可使用专业术语。"
        if any(kw in profession for kw in _INVENTOR_KEYWORDS):
            return "用户偏技术背景，适度通俗化专业术语。"
    return "保持专业但通俗的中文交流。"


# [S2-3] 画像 → 表达密度指令关键词。
# 代理人/律师：可高密度专业表达；发明人/工程师：需通俗化。
# 关键词判定优先级：专业身份在前（更明确），无命中则走中间档（不强行通俗也不堆术语）。
_PROFESSIONAL_KEYWORDS = ("代理人", "律师", "审查员", "知识产权", "patent attorney")
_INVENTOR_KEYWORDS = ("发明人", "工程师", "研究员", "开发者", "技术员")


def _profile_density_hint(profile_text: str) -> str:
    """据画像内容返回表达密度指令（让模型适配用户专业水平）。

    代理人/律师 → 可用高密度专利术语，无需过度解释。
    发明人/工程师 → 把术语翻译成大白话，必要时类比。
    其他/无法判定 → 维持默认（专业但通俗）。
    """
    if any(kw in profile_text for kw in _PROFESSIONAL_KEYWORDS):
        return "用户是专利专业人士，可使用高密度专利术语，无需过度解释基础概念。"
    if any(kw in profile_text for kw in _INVENTOR_KEYWORDS):
        return "用户是技术发明人，把专利术语翻译成大白话，必要时用类比，避免生硬法律术语。"
    return "保持专业但通俗的中文交流。"



def _retrieve_knowledge_for_section(
    db, user_id, section: Section, user_input: str | None = None,
) -> list[dict] | None:
    """为当前章节预检索知识库，失败静默返回 None（不阻断 agent 构建）。

    检索 query 由章节标题 + 章节目标 + 用户输入拼接构成。user_input 为空时
    仅用章节信号检索。top_k=3，单条内容截断到 300 字以控制 system prompt token。

    检索源：① 本地 RAG（pgvector）为主；② 用户开启 ima 实时检索源时，
    并行查 ima search_knowledge_base，返回 highlight 片段合并进来。
    ima 为 fail-open 外部源——任何失败静默跳过，不影响本地结果与 agent 构建。
    """
    try:
        from app.rag.retriever import retrieve
        from app.ai.section_prompts import get_section_prompt

        sp = get_section_prompt(section.key)
        parts = [section.title, sp.goal]
        if user_input and user_input.strip():
            parts.append(user_input.strip()[:200])
        query = " ".join(parts)

        results = retrieve(db, user_id=user_id, query=query, top_k=3)
        knowledge = [
            {
                "content": r.content[:300],
                "score": round(r.score, 2),
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]

        # ── ima 实时外部检索源（可选，fail-open）──
        # admin 在控制台配置并开启 ima 全局检索源后，每次预检索额外查 ima 知识库。
        # 独立 try/except：ima 失败绝不影响已拿到的本地结果。
        try:
            knowledge.extend(_retrieve_ima_for_section(db, query))
        except Exception:
            logger.warning("ima 外部检索失败，降级只用本地结果", exc_info=True)
            db.rollback()

        return knowledge if knowledge else None
    except Exception:
        logger.warning("知识预检索失败，降级不注入相关知识（不阻断生成）", exc_info=True)
        db.rollback()
        return None


def _retrieve_ima_for_section(db, query: str) -> list[dict]:
    """ima 外部检索源：全局开启时实时查 ima，返回统一片段结构。

    admin 未配置 / disabled / 调用失败 → 返回 []。成功则把 highlight 片段转成
    与本地结果同构的 dict（project_title 标记为「腾讯 ima」便于区分来源）。
    """
    from app.rag.ima_source import IMA_FALLBACK_SCORE, search_ima
    from app.services.ima_config_service import resolve_ima_config

    ima_cfg = resolve_ima_config(db)
    if ima_cfg is None:
        return []
    hits = search_ima(query, ima_cfg, top_k=3)
    return [
        {
            "content": (h.get("content") or "")[:300],
            "score": IMA_FALLBACK_SCORE,
            "section_key": None,
            "project_title": h.get("title") or "腾讯 ima",
        }
        for h in hits
    ]


def build_system_prompt(db, section: Section) -> str:
    """装配【静态】system prompt（agent loop 路线用，spec §3.1.1）。

    【批次 A prefix cache 改造（决策 D1）】只保留跨轮字节稳定的层：
    项目元信息 [L4] → 用户画像 → 当前章节策略 → 状态提示 → 角色定义。

    逐轮易变的层（已写章节全文、术语表、知识库检索结果、长期记忆、意图指令）
    全部迁移到 build_turn_reminder——随当轮用户消息尾部注入、落库剥离，
    使 [system + history] 前缀在连续轮次间逐字节不变，命中供应商前缀缓存
    （DeepSeek 命中价约为未命中的 1/10）。

    前文层从 system 迁出的取舍：已写章节/术语表在**同一章节的会话内**通常
    字节不变且体积可观——留在静态前缀可整段按命中价重复计费；被编辑时只
    付出一次冷启动 miss（预期行为）。若放易变块则每轮全价计费，得不偿失。
    """
    project = db.get(Project, section.project_id)
    sp = get_section_prompt(section.key)

    parts: list[str] = []

    # [L4] 项目元信息层（顶部，全局上下文）
    parts.append("# 当前交底书项目")
    parts.append(f"项目标题：{project.title}")
    if project.metadata_:
        meta_text = _format_metadata(project.metadata_)
        if meta_text:
            parts.append(f"项目背景信息：\n{meta_text}")

    # 用户画像层（静态稳定层）。预取 user_id 局部变量：下游读取失败会 rollback
    # 使 project 被 expire，局部变量避开惰性加载炸装配。
    project_user_id = project.user_id
    if project_user_id is not None:
        wp = _get_writing_profile(db, project_user_id)
        if wp is not None:
            lines = []
            if wp.profession:
                lines.append(f"- 职业身份：{wp.profession}")
            if wp.tech_domain:
                lines.append(f"- 技术领域：{wp.tech_domain}")
            if wp.writing_style:
                lines.append(f"- 写作风格偏好：{wp.writing_style}")
            if wp.terminology:
                lines.append(f"- 术语偏好：{wp.terminology}")
            density_hint = _proficiency_density_hint(wp.proficiency, wp.profession)
            if lines:
                parts.append("# 用户画像（请遵循其偏好与专业水平）")
                parts.append("\n".join(lines))
                parts.append(f"表达密度：{density_hint}")
        else:
            # fallback：旧版自由画像记忆（user_memory source=profile）
            profile = _get_profile_memories(db, project_user_id)
            if profile:
                profile_text = "\n".join(f"- {m.content}" for m in profile)
                density_hint = _profile_density_hint(profile_text)
                parts.append("# 用户画像")
                parts.append(profile_text)
                parts.append(f"表达密度：{density_hint}")

    # 章节策略层（当前章节聚焦）
    parts.append("# 当前正在撰写章节")
    parts.append(f"章节标题：【{section.title}】")
    parts.append(f"本章目标：{sp.goal}")
    # [S1] 知识资产激活：注入 guide_questions + completion_criteria。
    # 此前两字段定义了却从未注入——模型缺主动追问引导，也不知道「什么算写完」。
    # guide_questions 注入为「可追问要点」（非必答清单，避免模型机械逐条问）；
    # completion_criteria 让模型有明确的完成线（最直接的质量杠杆）。
    if sp.guide_questions:
        parts.append("引导要点（可主动追问用户，不必逐条回答）：")
        parts.append("\n".join(f"- {q}" for q in sp.guide_questions))
    parts.append(f"输出格式要求：{sp.output_format}")
    parts.append(f"达标判定：{sp.completion_criteria}")

    # [S4-1] few-shot 范例：给模型看「好样子」，照着结构和句式写。
    # 范例脱敏抽象（保留写法，技术内容通用化），控制 token（每段精炼）。
    # 无范例的章节（如 custom）跳过，不注入空段。
    if sp.few_shot_example:
        parts.append("# 参考范例（学习其结构与句式，不要照抄具体内容）")
        parts.append(sp.few_shot_example)

    # [S2-1] 章节状态行为提示：让模型据 empty/drafting/confirmed 切换策略
    status_hint = SECTION_STATUS_HINTS.get(section.status)
    if status_hint:
        parts.append(status_hint)

    # 角色定义层（最底部，兜底规范）
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)


def build_turn_reminder(
    db, section: Section, *,
    knowledge_context: list[dict] | None = None,
    user_input: str | None = None,
    intent: str | None = None,
) -> str:
    """装配【逐轮易变】上下文快照（批次 A 决策 D1）。

    返回值随当轮用户消息尾部注入（wrap_user_message），**不落库、不进历史回放**
    ——每轮快照独立存在，历史轮次的旧快照不参与计费也不干扰新判断。

    收录的易变层（从原 build_system_prompt 整体迁出，内容不变只换位置）：
    - 已写章节全文 + 一致性约束
    - 【T2】项目术语表（D13：术语表 > 沿用现状 > 最小改动）
    - 知识库检索结果（按 query 逐轮变化）
    - 用户长期记忆（检索命中 + 热门补位，hit_count 变化与 query 相关性均逐轮漂移）
    - [S2-2] 意图行为指令（由当轮输入分类决定）

    无任何可注入内容时返回空串（调用方跳过包裹，不留空标签）。
    """
    sp = get_section_prompt(section.key)
    blocks: list[str] = []

    # [前文直注入] 已写章节层（跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        blocks.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        blocks.append(written)
        # [S3-1] 一致性约束指令：沿用术语 / 呼应前文 / 不矛盾。
        blocks.append(
            "一致性要求：① 沿用上文已确立的术语，不要换同义词；"
            "② 本章节若涉及「技术问题」「技术方案」等前文章节，必须显式呼应其表述；"
            "③ 不要与上文的技术方案、技术效果矛盾。"
        )

    # 【T2】项目术语表层。每次装配现查（动态生效）；失败静默降级（防事务毒化）。
    try:
        term_lines = _project_terms_lines(db, section.project_id)
        if term_lines:
            blocks.extend(term_lines)
    except Exception:  # noqa: BLE001
        db.rollback()

    # 知识库预注入层
    if knowledge_context:
        kb = [
            "# 知识库参考（你历史案例中与本章节最相关的内容，请参考其术语与风格）",
        ]
        for k in knowledge_context:
            source = k.get("project_title") or "历史案例"
            key = f"·{k['section_key']}" if k.get("section_key") else ""
            score = k.get("score", 0)
            content = k.get("content", "")
            kb.append(f"- 《{source}》{key}（相关度 {score}）：{content}")
        kb.append(
            "使用规则：参考上述案例的术语体系和写作风格，自然地呼应其表述方式，"
            "不要逐字抄内容。若与当前项目无关则忽略。"
        )
        blocks.extend(kb)

    # 用户长期记忆层（检索命中 + 热门补位合并块）
    project = db.get(Project, section.project_id)
    project_user_id = project.user_id if project else None
    if project_user_id is not None:
        # 检索 query 选择：有用户输入用输入（最强语义信号），否则回退章节信号
        memory_query = (user_input.strip() if user_input and user_input.strip()
                        else f"{section.title} {sp.goal}")
        memories = _search_user_memories(db, project_user_id, memory_query)
        retrieved_ids = {getattr(m, "id", None) for m in memories}
        hot = _hot_user_memories(db, project_user_id, exclude_ids=retrieved_ids)
        merged = list(memories) + [m for m in hot if getattr(m, "id", None) not in retrieved_ids]
        if merged:
            mem_block = ["# 关于这位用户的长期记忆（请遵循其偏好与约定）"]
            mem_block.extend(f"- {m.content}" for m in merged)
            # [S3-2] 记忆使用规则
            mem_block.append(
                "记忆使用规则：这些是用户跨项目的稳定偏好/事实。【自然融入】表达，"
                "不要机械复读；与当前章节任务无关的记忆【忽略】；"
                "只在影响表达风格或领域判断时启用。"
            )
            blocks.extend(mem_block)

    # [S2-2] 意图行为提示：由当轮输入分类决定，天然逐轮变化。
    intent_hint = INTENT_HINTS.get(intent) if intent else None
    if intent_hint:
        blocks.append(intent_hint)

    return "\n\n".join(blocks)


def wrap_user_message(content: str, reminder: str) -> str:
    """把当轮易变快照包进 system-reminder 标签，附着在用户消息尾部。

    reminder 为空时原样返回（不留空壳标签）。标签内的说明句明确告知模型
    这是系统注入的非用户内容，避免模型把它当成用户的提问复读给用户。
    """
    if not reminder:
        return content
    return (
        f"{content}\n\n<system-reminder>\n"
        "以下是系统随本轮消息注入的参考上下文（非用户发言，请勿向用户复述）：\n"
        f"{reminder}\n"
        "</system-reminder>"
    )


# ── T2 项目术语表层（spec §3.3.3）────────────────────────────────────────────

# 注入条数上限：专利项目术语表通常 <50 条，100 条为防御性上限（超出截断 + warning）
_TERMS_INJECT_LIMIT = 100
# definition 注入截断（字符）——超限优先截断 definition 而非丢条目（spec §7 R4）
_TERM_DEFINITION_LIMIT = 200


def _project_terms_lines(db, project_id) -> list[str]:
    """装配项目术语表层 parts 行。空表/全 disabled 返回空列表（整层跳过）。

    失败由调用方 try/except 静默（防事务毒化）。
    """
    from sqlalchemy import select

    from app.models import ProjectTerm

    rows = db.scalars(
        select(ProjectTerm).where(
            ProjectTerm.project_id == project_id,
            ProjectTerm.enabled.is_(True),
        ).order_by(ProjectTerm.term)
    ).fetchmany(_TERMS_INJECT_LIMIT + 1)
    if not rows:
        return []
    if len(rows) > _TERMS_INJECT_LIMIT:
        logger.warning("项目术语表超过 %d 条，注入截断（project=%s）",
                       _TERMS_INJECT_LIMIT, project_id)
        rows = rows[:_TERMS_INJECT_LIMIT]

    lines = ["# 本项目术语表（写作与修订必须使用标准术语，禁止使用其变体）"]
    for r in rows:
        entry = r.term
        if r.variants:
            entry += f"（禁用：{'、'.join(r.variants)}）"
        if r.definition:
            definition = r.definition[:_TERM_DEFINITION_LIMIT]
            entry += f"：{definition}"
        lines.append(f"- {entry}")
    return lines
