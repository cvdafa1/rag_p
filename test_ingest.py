import asyncio
from app.core.logging import setup_logging
from app.core.queue import consume_ingest_tasks
from app.core.pipeline import parse_and_ingest
import logging
logger = logging.getLogger(__name__)


setup_logging()

async def worker_handler(task: dict):
    """Redis 里每弹出一条消息，就调这里"""
    logger.info(f'来新任务了:{task}')
    await parse_and_ingest(
        doc_id=task["doc_id"],
        file_path=task["file_path"],
        source_name=task["source_name"],
    )


async def main():
    await consume_ingest_tasks(worker_handler)

if __name__ == "__main__":
    asyncio.run(main())
