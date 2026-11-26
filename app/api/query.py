"""
问答 API

端点：
- POST /api/v1/ask  — 提问，返回答案 + 引用来源
- POST /api/v1/retrieve — 只检索不生成（调试用）
"""

import asyncio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.embedder import embed_text
from app.core.store import query_similar
from app.core.generator import generate
from app.models.document import Document
from sqlalchemy import select

router = APIRouter()


# ============================================================
# 请求 / 响应模型
# ============================================================

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    top_k: int | None = Field(None, ge=1, le=20, description="检索条数，默认用 config")
    distance_threshold: float | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]
    retrieved_count: int



class RetrieveRequest(BaseModel):
    question: str
    top_k: int | None = None
    distance_threshold: float | None = None


# ============================================================
# 端点
# ============================================================

@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    """
    主问答接口

    流程：
    1. 问题向量化
    2. Chroma 检索 Top-K
    3. 从 PG 补充文档详情
    4. 调 DeepSeek 生成回答
    """
    # ---- Step 1: 问题编码 ----
    question_vec = await embed_text(req.question)

    # ---- Step 2: 向量检索 ----
    top_k = req.top_k
    result = query_similar(question_vec, top_k, req.distance_threshold)

    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    if not ids:
        return AskResponse(
            answer="知识库中未找到相关内容。",
            sources=[],
            retrieved_count=0,
        )

    # ---- Step 3: 组装检索结果 ----
    contexts = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        contexts.append({
            "content": doc,
            "metadata": {
                **meta,
                "_distance": dist,     # 相似度距离（越小越相似）
            },
        })

    # ---- Step 4: 调 LLM 生成 ----
    llm_result = await generate(req.question, contexts)

    return AskResponse(
        answer=llm_result["answer"],
        sources=llm_result["sources"],
        retrieved_count=len(contexts),
    )


@router.post("/retrieve")
async def retrieve_only(req: RetrieveRequest):
    """
    调试用：只检索，不调 LLM
    方便验证 embedding + Chroma 检索质量
    """
    question_vec = await embed_text(req.question)
    result = query_similar(question_vec, req.top_k, req.distance_threshold)

    items = []
    for i, (doc, meta, dist) in enumerate(zip(
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    )):
        items.append({
            "rank": i + 1,
            "content": doc,
            "source": meta.get("source", ""),
            "chapter": meta.get("chapter", ""),
            "distance": round(dist, 4),
        })

    return {
        "query": req.question,
        "results": items,
        "total": len(items),
    }