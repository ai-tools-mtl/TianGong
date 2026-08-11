"""智慧芽 PatSnap 专利检索客户端。

照搬 rag/ima_source.py 模式：httpx 直连外部 API，无 key 时返回 Mock 桩数据。
拿到 key 后填 .env 的 PATENTSNAP_API_KEY 即可切真实检索，无需改代码。

智慧芽 OpenAPI 鉴权：Bearer token（OAuth2 client_credentials），与 ima 的自定义 header 不同。
真实对接时需先 POST /oauth/token 拿 access_token，再带 Bearer 查询。
MVP 阶段用 Mock 桩，key 为空时自动走 Mock。
"""
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Mock 桩数据：3 条经典专利样例（机械/电子/化学各一），无 key 时返回。
# 用于产品演示和开发测试，拿到真实 key 后自动切真实检索。
_MOCK_PATENTS = [
    {
        "title": "一种基于深度学习的图像识别方法及系统",
        "applicant": "XX科技有限公司",
        "patent_number": "CN110123456A",
        "abstract": "本发明涉及图像识别技术领域，具体公开了一种基于深度学习的图像识别方法及系统。该方法通过构建卷积神经网络模型，对输入图像进行特征提取和分类识别，提高了识别准确率和处理效率。",
        "url": "https://patents.google.com/patent/CN110123456A",
        "publication_date": "2019-08-09",
        "relevance": 0.95,
    },
    {
        "title": "一种新型机械传动装置",
        "applicant": "YY机械研究院",
        "patent_number": "CN105678901B",
        "abstract": "本发明公开了一种新型机械传动装置，包括主动齿轮、从动齿轮和传动轴。通过优化齿轮齿形和材料配比，实现了高扭矩传递下的低噪音运行，适用于工业自动化设备。",
        "url": "https://patents.google.com/patent/CN105678901B",
        "publication_date": "2018-03-15",
        "relevance": 0.88,
    },
    {
        "title": "一种锂离子电池正极材料及其制备方法",
        "applicant": "ZZ新能源股份有限公司",
        "patent_number": "CN109876543A",
        "abstract": "本发明涉及电池技术领域，具体涉及一种锂离子电池正极材料及其制备方法。该正极材料采用镍钴锰三元体系，通过共沉淀法和高温烧结工艺制备，具有高能量密度和优异的循环稳定性。",
        "url": "https://patents.google.com/patent/CN109876543A",
        "publication_date": "2019-06-04",
        "relevance": 0.82,
    },
]


def search_patents(query: str, *, top_k: int = 10) -> list[dict]:
    """检索专利。无 key 时返回 Mock 桩数据，有 key 时调智慧芽真实 API。

    返回统一形状：[{title, applicant, patent_number, abstract, url, publication_date, relevance}]
    """
    if not query.strip():
        return []

    settings = get_settings()

    # 无 key：走 Mock 桩（产品演示用）
    if not settings.patentsnap_api_key:
        logger.info("专利检索使用 Mock 桩数据（未配置 PATENTSNAP_API_KEY）")
        return _MOCK_PATENTS[:top_k]

    # 有 key：调智慧芽真实 API
    try:
        return _search_patentsnap(query, settings, top_k=top_k)
    except Exception as e:
        logger.warning("智慧芽专利检索失败，降级返回 Mock 桩: %s", e)
        return _MOCK_PATENTS[:top_k]


def _search_patentsnap(query: str, settings, *, top_k: int) -> list[dict]:
    """调智慧芽 OpenAPI 检索专利。

    智慧芽检索 API（Patent Search API）：
    POST {base_url}/patent/search
    Body: {{ "q": query, "limit": top_k }}
    Bearer token 鉴权。

    返回 [{title, applicant, patent_number, abstract, url, publication_date, relevance}]。
    字段映射按智慧芽 API 实际返回结构调整（拿到 key 后联调校准）。
    """
    resp = httpx.post(
        f"{settings.patentsnap_base_url}/patent/search",
        headers=_build_headers(settings),
        json={"q": query, "limit": top_k},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    # 智慧芽返回结构待联调确认，以下为预期映射
    items = data.get("data", {}).get("patents", [])
    return [
        {
            "title": p.get("title", ""),
            "applicant": p.get("current_assignee", "") or p.get("applicant", ""),
            "patent_number": p.get("patent_number", p.get("publication_number", "")),
            "abstract": p.get("abstract", ""),
            "url": f"https://patents.google.com/patent/{p.get('patent_number', '')}",
            "publication_date": p.get("publication_date", ""),
            "relevance": p.get("score", 0.5),
        }
        for p in items
    ]


def _build_headers(settings) -> dict[str, str]:
    """构造请求头（智慧芽 Bearer token 鉴权）。"""
    return {
        "Authorization": f"Bearer {settings.patentsnap_api_key}",
        "Content-Type": "application/json",
    }
