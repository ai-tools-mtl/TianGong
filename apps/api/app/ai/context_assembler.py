"""五层上下文装配（设计 5.4）。

[系统层] 角色 + 输出规范
[项目层] 已确认章节的 summary
[章节层] 当前章节的 Prompt 策略
[对话层] 本章节历史对话
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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
   只记跨项目稳定的信息（如「偏好简洁风格」「我做新能源电池」），不记项目内具体决策。"""


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
        db.rollback()
        return []


def _get_profile_memories(db, user_id):
    """[S2-3] 取用户画像记忆（source=profile）。失败静默返回空（不阻断 prompt 装配）。

    画像记忆存职业/领域/专业水平（如「用户是专利代理人，机械领域」），
    用于调节模型的表达密度。与 _search_user_memories 同样需 rollback 防事务毒化。
    """
    try:
        from app.services.memory_service import list_memories
        return list_memories(db, user_id=user_id, source="profile")
    except Exception:
        db.rollback()
        return []


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
        if not results:
            return None
        return [
            {
                "content": r.content[:300],
                "score": round(r.score, 2),
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]
    except Exception:
        return None


def build_system_prompt(
    db, section: Section, user_input: str | None = None, intent: str | None = None,
    knowledge_context: list[dict] | None = None,
) -> str:
    """装配动态 system prompt（agent loop 路线用，spec §3.1.1）。

    拼接顺序：项目元信息 [L4] → 已写章节 [前文直注入] → 当前章节策略 → 角色定义。

    项目元信息在顶部（全局不变量先建立上下文），角色定义在底部（行为规范在看到具体任务后理解更准确）。
    此顺序与原 assemble_messages 的拼接顺序保持心智模型统一。

    user_input（可选）：用户当前输入。用于记忆检索 query——用户刚说的话往往是最强的
    检索信号（如「检查我的写作风格」直接关联「偏好简洁风格」记忆）。MVP 策略：用户输入
    为主，章节信号（标题+目标）为辅，拼接检索。None 时（如非 chat 场景）回退到纯章节信号。

    intent（可选，S2-2）：用户意图（draft/edit/info/guide/none），由 classify_intent 识别。
    非 none 时注入对应行为指令，让模型据意图切换行为（代写/改写/答疑/引导）。
    None 或 "none" 时不注入意图段（走默认行为）。
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

    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)
        # [S3-1] 一致性约束指令：从「只注入」升级为「注入+约束」。
        # 此前只把前文塞进去，模型未必主动保持一致——显式约束三件事：
        # 沿用术语（避免同义换词）、呼应前文（技术方案要对准技术问题）、不矛盾。
        parts.append(
            "一致性要求：① 沿用上文已确立的术语，不要换同义词；"
            "② 本章节若涉及「技术问题」「技术方案」等前文章节，必须显式呼应其表述；"
            "③ 不要与上文的技术方案、技术效果矛盾。"
        )

    # 知识库预注入层：系统自动检索与当前章节最相关的历史案例，让 agent 从一开始就
    # 带着参考上下文工作。放在已写章节之后（同属结构性上下文），用户记忆之前。
    if knowledge_context:
        parts.append(
            "# 知识库参考（你历史案例中与本章节最相关的内容，请参考其术语与风格）"
        )
        for k in knowledge_context:
            source = k.get("project_title") or "历史案例"
            key = f"·{k['section_key']}" if k.get("section_key") else ""
            score = k.get("score", 0)
            content = k.get("content", "")
            parts.append(f"- 《{source}》{key}（相关度 {score}）：{content}")
        parts.append(
            "使用规则：参考上述案例的术语体系和写作风格，自然地呼应其表述方式，"
            "不要逐字抄内容。若与当前项目无关则忽略。"
        )

    # 【新增】用户长期记忆层（检索注入，纯检索式策略）
    # 检索 query 选择（实测：混拼会稀释语义信号，必须二选一）：
    # - 有 user_input（chat 场景）：只用用户输入。它是最强语义信号，
    #   如「检查我的写作风格」→命中「偏好简洁风格」记忆。
    # - 无 user_input（generate 等场景）：回退到章节标题+目标。
    # project 已在上方 fetch（L164），直接复用其 user_id，避免重复查询。
    if project.user_id is not None:
        # user_input 非空且非纯空格时用它检索；否则回退章节信号
        # （纯空格 embed 会产出垃圾向量，污染检索结果）
        memory_query = (user_input.strip() if user_input and user_input.strip()
                        else f"{section.title} {sp.goal}")
        memories = _search_user_memories(db, project.user_id, memory_query)
        if memories:
            memory_lines = "\n".join(f"- {m.content}" for m in memories)
            parts.append("# 关于这位用户的长期记忆（请遵循其偏好与约定）")
            parts.append(memory_lines)
            # [S3-2] 记忆使用规则：从「裸堆」升级为「注入+使用规则」。
            # 此前检索回来的记忆直接堆进去，没告诉模型何时用、怎么用——
            # 易导致机械复读无关记忆。显式三条规则：自然融入 / 不复读 / 无关忽略。
            parts.append(
                "记忆使用规则：这些是用户跨项目的稳定偏好/事实。【自然融入】表达，"
                "不要机械复读；与当前章节任务无关的记忆【忽略】；"
                "只在影响表达风格或领域判断时启用。"
            )

        # [S2-3] 用户画像层：source=profile 的记忆（职业/领域/专业水平），全量注入。
        # 画像不走语义检索（量少、要全量），用 list_memories(source=profile) 直取。
        # 据画像内容调节表达密度：代理人/律师 → 高密度专业术语；发明人/工程师 → 通俗化。
        profile = _get_profile_memories(db, project.user_id)
        if profile:
            profile_text = "\n".join(f"- {m.content}" for m in profile)
            density_hint = _profile_density_hint(profile_text)
            parts.append("# 用户画像")
            parts.append(profile_text)
            parts.append(f"表达密度：{density_hint}")

    # 章节策略层（底部偏上，当前章节聚焦）
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

    # [S2-2] 意图行为提示：让模型据用户意图（代写/改写/答疑/引导）切换行为。
    # intent=None 或 "none" 时跳过（走默认行为，不强分类，D1 决策）。
    intent_hint = INTENT_HINTS.get(intent) if intent else None
    if intent_hint:
        parts.append(intent_hint)

    # 角色定义层（最底部，兜底规范）
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)
