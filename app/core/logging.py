"""
日志配置模块

职责：
- 统一配置 logging，所有模块通过 logging.getLogger(__name__) 获取 logger
- 同时输出到：
    1. 控制台（INFO 及以上，带颜色，开发时看）
    2. 文件   （DEBUG 及以上，完整堆栈，持久化排查问题）
- 日志文件按日期滚动（每天一个新文件，保留 30 天）

用法（在任何模块里）：
    import logging
    logger = logging.getLogger(__name__)
    logger.info("something")
    logger.error("oops", exc_info=True)
"""

import logging
import logging.handlers
from pathlib import Path

from app.config import config


# ============================================================
# 常量
# ============================================================

LOG_DIR = Path("./data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "rag_service.log"
ERROR_LOG_FILE = LOG_DIR / "error.log"

# ============================================================
# Formatter
# ============================================================

class ColoredFormatter(logging.Formatter):
    """控制台用的彩色 formatter"""

    COLORS = {
        logging.DEBUG: "\033[36m",     # 青色
        logging.INFO: "\033[32m",      # 绿色
        logging.WARNING: "\033[33m",   # 黄色
        logging.ERROR: "\033[31m",     # 红色
        logging.CRITICAL: "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def _build_formatter(color=False):
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    if color:
        return ColoredFormatter(fmt, datefmt=datefmt)
    return logging.Formatter(fmt, datefmt=datefmt)


# ============================================================
# 全局 logger 配置（只初始化一次）
# ============================================================

_logger_configured = False


def setup_logging():
    """
    初始化根 logger 的 handler 和 level
    在 app/main.py 的 startup 里调用一次
    """
    global _logger_configured
    if _logger_configured:
        return
    _logger_configured = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根 logger 收全部，handler 自己过滤

    # ---- 防止重复添加 handler（reload 场景）----
    if root.handlers:
        root.handlers.clear()

    # ============================================================
    # Handler 1: 控制台（INFO+，彩色）
    # ============================================================
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(_build_formatter(color=True))
    root.addHandler(console_handler)

    # ============================================================
    # Handler 2: 主日志文件（DEBUG+，按日期滚动）
    # ============================================================
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when="midnight",       # 每天零点切一个新文件
        interval=1,
        backupCount=30,        # 保留 30 天
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"   # 文件名: rag_service.log.2026-11-24
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_build_formatter(color=False))
    root.addHandler(file_handler)

    # ============================================================
    # Handler 3: 错误日志文件（ERROR+，独立文件，方便排查）
    # ============================================================
    error_handler = logging.handlers.RotatingFileHandler(
        filename=ERROR_LOG_FILE,
        maxBytes=50 * 1024 * 1024,   # 50 MB 切一个
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(_build_formatter(color=False))
    root.addHandler(error_handler)

    # ============================================================
    # 第三方库降噪
    # ============================================================
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)

    root.info("📝 日志系统初始化完成")