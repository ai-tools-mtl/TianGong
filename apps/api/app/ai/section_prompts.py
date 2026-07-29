"""章节 Prompt 注册表（设计 5.5）。

每种章节 key 对应一套引导策略：目标、引导问题、输出格式、完成判定。
这是天工的「知识资产」，沉淀专利交底书的专业 know-how。
"""

from dataclasses import dataclass


@dataclass
class SectionPrompt:
    key: str
    goal: str
    guide_questions: list[str]
    output_format: str
    completion_criteria: str


SECTION_PROMPTS: dict[str, SectionPrompt] = {
    "name": SectionPrompt(
        key="name",
        goal="提炼一个清晰、准确的发明名称",
        guide_questions=[
            "这个发明最核心的功能是什么？",
            "它应用在什么领域？",
            "它是一个产品、方法，还是两者结合？",
        ],
        output_format="名称应为：<技术领域>+<核心特征>+<类型>",
        completion_criteria="名称 ≤25字，包含技术领域和核心特征",
    ),
    "field": SectionPrompt(
        key="field",
        goal="明确发明所属的技术领域",
        guide_questions=[
            "这个发明属于哪个技术领域？",
            "它涉及哪些专业技术分类？",
        ],
        output_format="一段简短的技术领域说明",
        completion_criteria="明确指出技术领域和大类",
    ),
    "background": SectionPrompt(
        key="background",
        goal="描述现有技术的现状和不足",
        guide_questions=[
            "目前这个领域有哪些现有技术？",
            "现有技术存在什么问题或不足？",
            "为什么需要改进？",
        ],
        output_format="背景技术应包含：现有技术描述 + 存在的问题",
        completion_criteria="至少描述一种现有技术及其不足",
    ),
    "problem": SectionPrompt(
        key="problem",
        goal="明确发明要解决的技术问题",
        guide_questions=[
            "这个发明针对什么技术问题？",
            "解决这个问题的意义是什么？",
            "注意：这里要陈述的是『技术问题』而非商业/市场问题——专利法只保护技术方案的改进",
        ],
        output_format="发明目的与技术问题的清晰陈述",
        completion_criteria="明确指出要解决的技术问题",
    ),
    "solution": SectionPrompt(
        key="solution",
        goal="完整描述解决技术问题的技术方案",
        guide_questions=[
            "方案的整体结构/流程是怎样的？",
            "有哪些关键组件/步骤？它们如何配合？",
            "方案的每个关键组件，具体解决『技术问题』里的哪个子问题？",
            "有没有替代实现方式？",
        ],
        output_format="技术方案应包含：整体架构 + 关键要素 + 工作原理",
        completion_criteria="至少覆盖结构、流程、关键要素三个维度，且必须显式呼应『技术问题』章节的表述",
    ),
    "effect": SectionPrompt(
        key="effect",
        goal="阐述发明带来的有益效果",
        guide_questions=[
            "相比现有技术，这个方案有什么优势？",
            "能带来哪些具体的效果（性能/成本/效率）？尽量给出可量化数据或对比",
            "每个效果与技术方案的哪个组件直接相关？",
        ],
        output_format="有益效果应具体、可量化",
        completion_criteria="至少描述一个有益效果并与技术方案对应，尽量给出可量化数据",
    ),
    "drawings": SectionPrompt(
        key="drawings",
        goal="描述附图内容及图注",
        guide_questions=[
            "有哪些附图？每张图展示什么？",
            "用一两句话描述每张图的内容。",
        ],
        output_format="图N：<图的内容描述>",
        completion_criteria="每张图有对应的图注说明",
    ),
    "embodiment": SectionPrompt(
        key="embodiment",
        goal="详细描述发明的具体实施方式",
        guide_questions=[
            "能否给出一个具体的实施例？",
            "实施例中各部件/步骤的具体参数是什么？",
            "有没有其他变形实施方式？",
        ],
        output_format="具体实施方式应包含至少一个完整实施例",
        completion_criteria="至少一个实施例，与技术方案对应",
    ),
    "custom": SectionPrompt(
        key="custom",
        goal="根据章节标题引导用户撰写内容",
        guide_questions=[
            "这部分您想表达的核心信息是什么？",
            "有没有需要特别强调的关键点或数据？",
            "是否需要配合图示或示例说明？",
        ],
        output_format="结构清晰的段落/列表",
        completion_criteria="内容与标题相关，无空白",
    ),
}


def get_section_prompt(key: str) -> SectionPrompt:
    """获取章节 Prompt 策略。未知 key 返回 custom。"""
    return SECTION_PROMPTS.get(key, SECTION_PROMPTS["custom"])
