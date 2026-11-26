"""
入库管道编排器

职责：
  串联 converter → cleaner → splitter → embedder → store → PG 状态回写
  由 Worker 消费 Redis 任务后调用

数据流：
  1. 从 file_path 读取原始文件
  2. converter: 转成 Markdown（当前阶段：.md 直接读，其他格式 TODO 接 Docling）
  3. cleaner: 清洗
  4. splitter: 切分
  5. embedder: 批量编码
  6. store: 写入 Chroma
  7. PG: 更新 documents 表状态 + 写 document_versions 表
"""

import asyncio
import uuid
from pathlib import Path

from app.config import config
from app.core.cleaner import clean_markdown
from app.core.splitter import split_document
from app.core.embedder import embed_batch, build_embed_text
from app.core.store import upsert_chunks, delete_by_doc_id
from app.core.db import AsyncSessionLocal
from app.models.document import Document, DocumentVersion
from sqlalchemy import select, update
from app.core.parsers import parse_file
import logging

logger = logging.getLogger(__name__)

async def parse_and_ingest(doc_id: str, file_path: str, source_name: str):
    """
    Worker 调用的主函数

    参数：
      - doc_id:      文档 UUID（字符串）
      - file_path:   原始文件在磁盘上的路径
      - source_name: 推断出的文档名（不带版本号）
    """
    # ---- Step 1: 读取原始文件 ----
    try:
        raw_text = parse_file(file_path)
    except ValueError as e:
        logger.error(f"解析失败: {e}")
        return
    logging.info(f'文件读取成功:文件长度({len(raw_text)})')

    # ---- Step 2: 清洗 ----
    clean_text = clean_markdown(raw_text)

    # ---- Step 3: 切分 ----
    chunks = split_document(clean_text, doc_id, source_name)

    if not chunks:
        # 切分结果为空（文档太小），标记失败
        await _update_status(doc_id, "failed", error_msg="文档内容过少，无法切分")
        return

    # ---- Step 4: 批量嵌入 ----
    # 4a. 给每个 chunk 拼前缀文本
    embed_texts = [
        build_embed_text(
            source=source_name,
            chapter=c.chapter,
            content=c.content,
        )
        for c in chunks
    ]

    # 4b. 批量编码（扔线程池，不阻塞事件循环）
    embeddings = await embed_batch(embed_texts)

    # ---- Step 5: 组装写入 Chroma ----
    chunk_dicts = []
    chunk_ids = []

    for chunk, emb in zip(chunks, embeddings):
        cid = chunk.chunk_id
        chunk_ids.append(cid)
        chunk_dicts.append({
            "chunk_id": cid,
            "content": chunk.content,
            "embedding": emb,
            "source": source_name,
            "chapter": chunk.chapter,
            "doc_id": doc_id,
            "version": "v1.0",  # TODO: 从 PG 查当前版本
        })

    # 5a. 如果是更新（同 doc_id 已有旧版本），先删旧 chunks
    delete_by_doc_id(doc_id)

    # 5b. 写入新 chunks
    upsert_chunks(chunk_dicts)

    # ---- Step 6: 更新 PG ----
    await _update_status(
        doc_id,
        status="active",
        chunk_count=len(chunks),
    )
    await _insert_version(doc_id, chunk_ids, file_path)

    logger.info(f"✅ [{source_name}] 入库完成: {len(chunks)} chunks, doc_id={doc_id}")


# ============================================================
# 内部工具
# ============================================================

def _read_file(file_path: str) -> str:
    """
    读取文件内容

    当前阶段：.md 直接读文本
    TODO: .docx / .pdf 接入 Docling 转换
    """
    p = Path(file_path)
    suffix = p.suffix.lower()

    if suffix == ".md":
        return p.read_text(encoding="utf-8")
    elif suffix == ".docx":
        # TODO: 接入 Docling
        raise NotImplementedError(f".docx 转换待接入 Docling: {file_path}")
    elif suffix == ".pdf":
        # TODO: 接入 Docling
        raise NotImplementedError(f".pdf 转换待接入 Docling: {file_path}")
    else:
        return p.read_text(encoding="utf-8", errors="ignore")


async def _update_status(
    doc_id: str,
    status: str,
    chunk_count: int = 0,
    error_msg: str = None,
):
    """更新 documents 表状态"""
    async with AsyncSessionLocal() as db:
        stmt = (
            update(Document)
            .where(Document.doc_id == uuid.UUID(doc_id))
            .values(
                status=status,
                chunk_count=chunk_count,
                error_msg=error_msg,
            )
        )
        await db.execute(stmt)
        await db.commit()


async def _insert_version(doc_id: str, chunk_ids: list, file_path: str):
    """写 document_versions 表"""
    async with AsyncSessionLocal() as db:
        ver = DocumentVersion(
            doc_id=uuid.UUID(doc_id),
            version="v1.0",
            filename=Path(file_path).name,
            file_path=file_path,
            chunk_ids=chunk_ids,
            status="active",
        )
        db.add(ver)
        await db.commit()
