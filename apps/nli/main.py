"""NLI 矛盾判断微服务。

用 sentence-transformers 的 CrossEncoder 原生加载 cross-encoder/nli-deberta-v3-base，
提供支持 [premise, hypothesis] 句子对配对的 /nli 端点。

为何自建而非复用 Infinity：Infinity 的 /classify 只支持单句分类（ClassifyInput.input
是 conlist(str)），不支持 NLI 必需的句子对输入。CrossEncoder.predict([(p, h)]) 才是
NLI 的正确用法——把两句话作为一对送入 cross-encoder，输出 contradiction/entailment/neutral。

模型模块级加载（应用启动时一次性载入 ~700MB 权重并预热），避免每次请求重复加载。
"""
import os
import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sentence_transformers import CrossEncoder

logger = logging.getLogger("nli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 模型路径：容器内挂载到 /data/models/nli-deberta-v3-base，本地开发用环境变量或相对路径。
# 环境变量 NLI_MODEL_DIR 由 docker-compose 注入（${NLI_MODEL_DIR:-./models/nli-deberta-v3-base}）。
MODEL_PATH = os.environ.get("NLI_MODEL_PATH", "/data/models/nli-deberta-v3-base")

logger.info("加载 NLI 模型: %s", MODEL_PATH)
# 模块级加载：启动时载入一次，常驻内存。CrossEncoder 默认 CPU（不指定 device）。
# nli-deberta-v3-base 约 700MB，加载需数秒；predict 单次 CPU 毫秒级。
model = CrossEncoder(MODEL_PATH)
# 预热：跑一次空推理，触发懒加载的算子初始化，避免首请求慢。
model.predict([("warmup", "warmup")], apply_softmax=True)
logger.info("NLI 模型就绪")

app = FastAPI(title="TianGong NLI Service")


class NliRequest(BaseModel):
    """NLI 请求：一对句子。"""
    premise: str = Field(..., min_length=1, description="前提句")
    hypothesis: str = Field(..., min_length=1, description="假设句")


class NliResponse(BaseModel):
    """NLI 响应：关系标签 + 置信度。"""
    label: str  # contradiction / entailment / neutral
    score: float


@app.get("/health")
def health():
    """健康检查。模型模块级加载，能响应即代表就绪。"""
    return {"status": "ok"}


@app.post("/nli", response_model=NliResponse)
def nli(req: NliRequest):
    """判定 premise 与 hypothesis 的关系：contradiction / entailment / neutral。

    CrossEncoder.predict([(p, h)], apply_softmax=True) 返回每对的概率分布（行数为 1），
    按 id2label 映射 argmax 即得标签。
    """
    probs = model.predict([(req.premise, req.hypothesis)], apply_softmax=True)[0]
    # id2label: {0: "contradiction", 1: "entailment", 2: "neutral"}（nli-deberta-v3-base）
    idx = int(probs.argmax())
    label = model.config.id2label[idx]
    score = float(probs[idx])
    return NliResponse(label=label, score=score)
