"""
Chroma 向量数据库封装

职责：
- 管理 Chroma 客户端和 collection 的单例（全局只初始化一次）
- 提供 chunks 的写入（upsert）、检索（query）、删除（按 doc_id）
- 所有向量和原文都经过这里进出 Chroma

其他模块不直接碰 Chroma，只调这里的函数。
"""

import chromadb
from chromadb.config import Settings
from app.config import config
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 全局单例（进程内只创建一次，避免重复连接）
# ============================================================

_client = None      # Chroma 底层客户端
_collection = None  # 当前使用的 collection


def get_client():
    """
    获取 Chroma 客户端（单例）
    使用 PersistentClient → 数据落盘到 config 指定的目录，进程重启不丢
    """
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=config.vector_store.persist_dir,   # ./data/chroma
            settings=Settings(anonymized_telemetry=False),  # 关掉遥测
        )
    return _client


def get_collection():
    """
    获取（或创建）collection（单例）
    collection 相当于关系数据库里的一张"表"
    这里用余弦相似度做向量距离度量
    """
    global _collection
    if _collection is None:
        _collection = get_client().get_or_create_collection(
            name=config.vector_store.collection_name,  # "enterprise_kb"
            metadata={"hnsw:space": "cosine"},        # 余弦相似度
        )
    return _collection


# ============================================================
# CRUD 操作
# ============================================================

def upsert_chunks(chunks: list[dict]):
    """
    批量写入（或更新）chunks 到 Chroma

    参数 chunks 中每条记录包含：
      - chunk_id:  唯一标识，如 "a3f2c1e8-..._C01"
      - content:   原始干净文本（不带前缀，给用户看的）
      - embedding: 768 维向量（带前缀的文本送入 BGE 得到的）
      - source:    文档名，如 "差旅管理制度 v2.1"
      - chapter:   章节路径，如 "第三章 > 3.2 住宿费"
      - doc_id:    UUID，关联到 PG 里的 documents 表
      - version:   版本号

    Chroma 里存的：
      - ids[]        → chunk_id
      - documents[]  → content（检索时取出来拼 Prompt）
      - embeddings[] → 向量（用于相似度计算）
      - metadatas[]  → {doc_id, source, chapter, version}（过滤和溯源用）
    """
    collection = get_collection()

    collection.upsert(
        ids=[c["chunk_id"] for c in chunks],
        documents=[c["content"] for c in chunks],
        embeddings=[c["embedding"] for c in chunks],
        metadatas=[
            {
                "doc_id": c.get("doc_id", ""),
                "source": c.get("source", ""),
                "chapter": c.get("chapter", ""),
                "version": c.get("version", ""),
            }
            for c in chunks
        ],
    )


def query_similar(embedding: list[float], top_k: int = None, distance_threshold: float = 0.55) -> dict:
    """
    向量检索：给定一个问题向量，返回最相似的 Top-K chunks

    参数：
      - embedding: 用户问题经 BGE 编码后的向量
      - top_k:    返回几条，不传则用 config 里的默认值（5）

    返回：
      Chroma 原始结果 dict，结构：
      {
        "ids":       [[id1, id2, ...]],
        "documents": [[text1, text2, ...]],
        "metadatas": [[{doc_id, source, chapter, version}, ...]],
        "distances": [[0.23, 0.31, ...]]    ← 距离越小越相似
      }
    """
    collection = get_collection()
    k = top_k or config.retrieve.top_k
    raw = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    # ---- 核心过滤逻辑 ----
    ids = raw["ids"][0]
    documents = raw["documents"][0]
    metadatas = raw["metadatas"][0]
    distances = raw["distances"][0]

    filtered = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }

    kept = 0
    for i in range(len(ids)):
        if distances[i] <= distance_threshold:
            filtered["ids"][0].append(ids[i])
            filtered["documents"][0].append(documents[i])
            filtered["metadatas"][0].append(metadatas[i])
            filtered["distances"][0].append(distances[i])
            kept += 1

    if kept == 0:
        # 全部被过滤了，返回空
        filtered = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    return filtered


def delete_by_doc_id(doc_id: str):
    """
    按 doc_id 删除所有关联的 chunks

    使用场景：文档版本更新时，先删旧版本的所有 chunks，再写入新的
    Chroma 的 where 过滤 → 匹配 metadata 中 doc_id 字段
    """
    collection = get_collection()
    collection.delete(where={"doc_id": doc_id})


def get_collection_count() -> int:
    """返回当前 collection 里总共有多少条记录（调试用）"""
    return get_collection().count()