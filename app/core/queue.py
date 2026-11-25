import json
import redis.asyncio as redis
from app.config import config
import logging
import asyncio


logger = logging.getLogger(__name__)
_redis = None


async def get_redis() -> Redis:
    global _redis
    
    # 如果已有连接，先 ping 一下看是否还活着
    if _redis is not None:
        try:
            await asyncio.wait_for(_redis.ping(), timeout=3)
            return _redis
        except Exception:
            # 连接已死，重建
            _redis = None
    
    import platform
    
    kwargs = dict(
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
        socket_keepalive=True,       # Windows 支持这个
        health_check_interval=30,
        max_connections=20,
    )
    
    # Windows 不支持 TCP_KEEPIDLE/TCP_KEEPINTVL 等参数
    if platform.system() != "Windows":
        import socket
        kwargs["socket_keepalive_options"] = {
            socket.TCP_KEEPIDLE: 60,
            socket.TCP_KEEPINTVL: 10,
            socket.TCP_KEEPCNT: 3,
        }
    
    _redis = await redis.from_url(
        config.queue.redis_url,
        **kwargs,
    )
    return _redis


async def publish_ingest_task(doc_id: str, file_path: str, source_name: str):
    r = await get_redis()
    await r.rpush(
        config.queue.queue_name,
        json.dumps({
            "doc_id": doc_id,
            "file_path": file_path,
            "source_name": source_name,
        }),
    )
    logger.info(f'任务已入队列:{file_path}-{source_name}')


async def consume_ingest_tasks(handler):
    """
    消费队列任务（带自动重连 + 异常兜底）
    
    handler: async callable(task: dict)
    """
    queue_name = config.queue.queue_name
    logger.info(f"🎧 Worker 启动，监听队列: {queue_name}")

    while True:
        r = None
        try:
            # 每次循环重新拿连接（利用连接池）
            r = await get_redis()
            
            # 先 ping 一下，检测连接是否还活着
            try:
                await asyncio.wait_for(r.ping(), timeout=3)
            except (asyncio.TimeoutError, ConnectionError):
                logger.warning("⚠️ Redis 连接已断开，等待重连...")
                await asyncio.sleep(2)
                continue

            # brpop 带超时兜底
            raw = await asyncio.wait_for(
                r.brpop(queue_name, timeout=5),
                timeout=10,  # 外层兜底，防止 brpop 本身卡死
            )

            if not raw:
                continue
            task = json.loads(raw[1])
            logger.info(f"📥 收到任务: doc_id={task.get('doc_id')}")

            # 执行任务（handler 内部自己处理业务异常）
            await handler(task)

            logger.info(f"✅ 任务完成: doc_id={task.get('doc_id')}")

        except asyncio.TimeoutError:
            # brpop 超时是正常的（队列空），不打 error
            continue

        except json.JSONDecodeError as e:
            logger.error(f"❌ 消息反序列化失败: {e}")

        except ConnectionError as e:
            logger.error(f"❌ Redis 连接断开: {e}，2秒后重连")
            await asyncio.sleep(2)

        except Exception as e:
            logger.exception(f"❌ 任务处理异常: {e}")
            # 失败的任务重新入队（最多重试3次的逻辑可以后面加）
            if 'task' in dir() and task:
                try:
                    retry_count = task.get("_retry", 0)
                    if retry_count < 3:
                        task["_retry"] = retry_count + 1
                        r = await get_redis()
                        await r.rpush(queue_name, json.dumps(task))
                        logger.warning(f"🔄 任务重新入队 (第{task['_retry']}次): doc_id={task.get('doc_id')}")
                    else:
                        await r.rpush(f"{queue_name}:failed", json.dumps(task))
                        logger.error(f"💀 任务彻底失败，移入死信队列: doc_id={task.get('doc_id')}")
                except Exception as re:
                    logger.error(f"❌ 重新入队也失败了: {re}")

        finally:
            # 不主动关闭连接（连接池管理），但确保引用释放
            r = None