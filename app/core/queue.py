import json
import redis.asyncio as redis
from app.config import config

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = await redis.from_url(
            config.queue.redis_url,
            decode_responses=True,
        )
    return _redis


async def publish_ingest_task(doc_id: str, file_path: str, source_name: str):
    r = await get_redis()
    await r.lpush(
        config.queue.queue_name,
        json.dumps({
            "doc_id": doc_id,
            "file_path": file_path,
            "source_name": source_name,
        }),
    )


async def consume_ingest_tasks(self, handler):
    """handler: async callable(task: dict)"""
    r = await get_redis()
    while True:
        raw = await r.brpop(config.queue.queue_name, timeout=5)
        if raw:
            task = json.loads(raw[1])
            await handler(task)