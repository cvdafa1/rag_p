"""
文档管理 API

端点：
- GET  /api/v1/documents       — 列表（分页、按状态筛选）
- GET  /api/v1/documents/{id}  — 详情
- GET  /api/v1/documents/{id}/chunks — 查看某个文档的 chunk 预览
- POST /api/v1/documents/{id}/reparse — 触发重新解析
- DELETE /api/v1/documents/{id} — 删除文档（PG + Chroma）
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime
from app.core.db import get_db
from app.models.document import Document
from app.core.store import delete_by_doc_id, get_collection_count
from uuid import UUID as UUID_Type

router = APIRouter()


# ============================================================
# 响应模型
# ============================================================

class DocumentItem(BaseModel):
    doc_id: UUID_Type
    source_name: str
    filename: str
    version: str
    status: str
    chunk_count: int
    uploader: str | None
    dept: str | None
    created_at: datetime | None

    class Config:
        from_attributes = True


# ============================================================
# 端点
# ============================================================

@router.get("/documents", response_model=dict)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """文档列表（分页 + 可选状态过滤）"""
    stmt = select(Document)
    if status:
        stmt = stmt.where(Document.status == status)

    # 总数
    count_stmt = select(func.count()).select_from(Document)
    if status:
        count_stmt = count_stmt.where(Document.status == status)
    total = (await db.execute(count_stmt)).scalar()

    # 分页
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for r in rows:
        items.append({
            "doc_id": str(r.doc_id),
            "source_name": r.source_name,
            "filename": r.filename,
            "version": r.version,
            "status": r.status,
            "chunk_count": r.chunk_count,
            "uploader": r.uploader,
            "dept": r.dept,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            DocumentItem.model_validate(r).model_dump(mode="json")
            for r in rows
        ],
    }


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    """文档详情"""
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id format")

    doc = (await db.execute(
        select(Document).where(Document.doc_id == uid)
    )).scalar_one_or_none()

    if not doc:
        raise HTTPException(404, "document not found")

    return {
        "doc_id": str(doc.doc_id),
        "source_name": doc.source_name,
        "filename": doc.filename,
        "version": doc.version,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "uploader": doc.uploader,
        "dept": doc.dept,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "file_hash": doc.file_hash,
        "error_msg": doc.error_msg,
    }


@router.get("/documents/{doc_id}/chunks")
async def preview_chunks(doc_id: str, limit: int = Query(5, ge=1, le=20)):
    """预览某个文档的前 N 个 chunks（从 Chroma 取）"""
    from app.core.store import get_collection

    coll = get_collection()
    result = coll.get(
        where={"doc_id": doc_id},
        limit=limit,
        include=["documents", "metadatas"],
    )

    items = []
    for cid, doc, meta in zip(
        result["ids"],
        result["documents"],
        result["metadatas"],
    ):
        items.append({
            "chunk_id": cid,
            "chapter": meta.get("chapter", ""),
            "source": meta.get("source", ""),
            "content_preview": doc[:150] + "..." if len(doc) > 150 else doc,
            "char_count": len(doc),
        })

    return {
        "doc_id": doc_id,
        "chunks_returned": len(items),
        "chunks": items,
    }


@router.post("/documents/{doc_id}/reparse")
async def reparse_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    """触发重新解析（更新版本）"""
    from app.core.queue import publish_ingest_task

    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id format")

    doc = (await db.execute(
        select(Document).where(Document.doc_id == uid)
    )).scalar_one_or_none()

    if not doc:
        raise HTTPException(404, "document not found")

    # 更新状态为 processing
    doc.status = "processing"
    await db.commit()

    # 重新发任务
    await publish_ingest_task(doc_id, doc.file_path, doc.source_name)

    return {"doc_id": doc_id, "status": "processing", "message": "已触发重新解析"}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    """删除文档：Chroma chunks + PG 记录"""
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id format")

    doc = (await db.execute(
        select(Document).where(Document.doc_id == uid)
    )).scalar_one_or_none()

    if not doc:
        raise HTTPException(404, "document not found")

    # 1. 删 Chroma
    delete_by_doc_id(doc_id)

    # 2. 删 PG
    await db.delete(doc)
    await db.commit()

    return {"doc_id": doc_id, "deleted": True}