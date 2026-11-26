import uuid
import hashlib
from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, AsyncSessionLocal
from app.core.queue import publish_ingest_task
from app.models.document import Document
from app.config import config

router = APIRouter()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    uploader: str | None = None,
    dept: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # 1. 校验扩展名
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in config.ingest.allowed_extensions:
        return {"error": f"不支持的文件类型 {ext}"}

    # 2. 读文件内容
    content = await file.read()
    file_hash = _sha256(content)

    # 3. 去重检查
    from sqlalchemy import select
    existing = await db.execute(
        select(Document).where(Document.file_hash == file_hash).limit(1)
    )
    if existing.scalar_one_or_none():
        return {"error": "该文件已存在", "file_hash": file_hash}

    # 4. 生成 doc_id + 存文件
    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}_{file.filename}"
    file_path = f"{config.ingest.raw_dir}/{safe_name}"
    with open(file_path, "wb") as f:
        f.write(content)

    # 5. 推断 source_name（从文件名去扩展名和版本号）
    source_name = file.filename.rsplit(".", 1)[0]
    for v in ["_v2.1", "_v2.0", "_v1.0"]:
        source_name = source_name.replace(v, "")

    # 6. 注册 PG
    doc = Document(
        doc_id=uuid.UUID(doc_id),
        source_name=source_name,
        filename=file.filename,
        file_path=file_path,
        file_hash=file_hash,
        status="processing",
        uploader=uploader,
        dept=dept,
    )
    db.add(doc)
    await db.commit()

    # 7. 发任务到 Redis
    await publish_ingest_task(doc_id, file_path, source_name)

    return {
        "doc_id": doc_id,
        "status": "processing",
        "message": "文件已接收，后台处理中",
    }