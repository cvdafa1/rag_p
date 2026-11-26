import asyncio
import logging

from fastapi import FastAPI
from app.api.ingest import router as ingest_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.core.db import init_db
from app.core.pipeline import parse_and_ingest
from app.core.queue import consume_ingest_tasks
from app.core.logging import setup_logging
from fastapi.middleware.cors import CORSMiddleware


# ---- 先配日志（尽早，其他 import 之前就生效）----
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Enterprise RAG Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 测试期放开，上线收窄成具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




app.include_router(ingest_router, prefix="/api/v1", tags=["ingest"])
app.include_router(query_router, prefix="/api/v1", tags=["query"])
app.include_router(documents_router, prefix="/api/v1", tags=["documents"])


async def worker_handler(task: dict):
    """Redis 里每弹出一条消息，就调这里"""
    logger.info(f'来新任务了:{task}')
    await parse_and_ingest(
        doc_id=task["doc_id"],
        file_path=task["file_path"],
        source_name=task["source_name"],
    )


@app.on_event("startup")
async def startup():
    await init_db()
    # 保存引用，防止被 GC 回收
    app.state.ingest_worker = asyncio.create_task(
        consume_ingest_tasks(worker_handler)
    )
    print("✅ 数据库初始化完成")


@app.get("/health")
async def health():
    return {"status": "ok"}

