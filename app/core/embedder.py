"""
BGE-small-zh-v1.5 嵌入模型封装

职责：
- 加载 BGE 模型（全局单例，启动时加载一次）
- 提供同步嵌入函数（给线程池调用）
- 提供异步嵌入函数（给 FastAPI 路由和 Worker 调用，不阻塞事件循环）
- 提供前缀拼接工具（入库时给每个 chunk 加"文档名 | 章节 | 内容"前缀）

为什么嵌入要异步包装？
  BGE 的 encode() 是 CPU/GPU 密集计算，如果在 async 函数里直接调，
  事件循环会被卡住，其他请求全部排队。
  所以把同步调用扔进线程池（run_in_executor），事件循环继续转。
"""

import asyncio
from sentence_transformers import SentenceTransformer
from app.config import config

# ============================================================
# 全局单例
# ============================================================

_model = None   # SentenceTransformer 实例，进程内只加载一次


def _get_model():
    """
    懒加载 BGE 模型
    第一次调用时才加载（约几百 MB 到内存），之后复用
    """
    global _model
    if _model is None:
        _model = SentenceTransformer(
            config.embed.model_name,   # "BAAI/bge-small-zh-v1.5"
            device=config.embed.device, # "cpu" 或 "cuda"
        )
    return _model


# ============================================================
# 同步函数（实际干活的，跑在线程池里）
# ============================================================

def _embed_single(text: str) -> list[float]:
    """
    同步：单条文本 → 向量
    用于问答时把用户问题编码成向量
    """
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)  # L2 归一化
    return vec.tolist()


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    同步：批量文本 → 向量列表
    用于入库时把几十个 chunks 一起编码（比逐条快很多）
    """
    model = _get_model()
    vecs = model.encode(
        texts,
        batch_size=config.embed.batch_size,  # 16
        normalize_embeddings=True,
    )
    return vecs.tolist()


# ============================================================
# 异步接口（给业务代码调用的）
# ============================================================

async def embed_text(text: str) -> list[float]:
    """
    异步单条嵌入
    内部把同步函数扔到默认线程池执行，不阻塞事件循环

    用法：
        vec = await embed_text("出差住宿标准是多少？")
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_single, text)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    异步批量嵌入
    入库管道调用：一次把 10~100 个 chunk 的 embed_text 全部编码

    用法：
        vecs = await embed_batch(["前缀文本1", "前缀文本2", ...])
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_batch, texts)


# ============================================================
# 工具函数
# ============================================================

def build_embed_text(source: str, chapter: str, content: str) -> str:
    """
    按 config 里的前缀模板拼接嵌入文本

    模板："{source} | {chapter} | {content}"
    拼出来： "差旅管理制度 v2.1 | 第三章 > 3.2 住宿费 | 一线城市不超过500元/晚……"

    为什么加前缀？
      BGE 训练时做了前缀增强，嵌入前拼上来源和章节信息，
      能让向量同时捕捉"这段内容是什么"和"它来自哪里"，
      检索时来源和章节的匹配度也会提高。

    注意：这个拼好的文本只送进 BGE 算向量，
    不存为 chunk 的 content（content 存的是干净原文）。
    """
    return config.embed.prefix_template.format(
        source=source,
        chapter=chapter,
        content=content,
    )