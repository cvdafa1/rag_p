from fastapi import FastAPI
from app.api.ingest import router as ingest_router
from app.core.db import init_db

app = FastAPI(title="Enterprise RAG Service", version="0.1.0")

app.include_router(ingest_router, prefix="/api/v1", tags=["ingest"])


@app.on_event("startup")
async def startup():
    await init_db()
    print("✅ 数据库初始化完成")


@app.get("/health")
async def health():
    return {"status": "ok"}