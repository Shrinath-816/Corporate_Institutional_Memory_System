"""
Module: config/logging_config.py

Purpose:
    Centralized logging configuration for the Institutional Memory System.

Responsibilities:
    - Configure Loguru as the sole logging backend for the entire system.
    - Intercept standard Python `logging` module calls and route them through Loguru.
    - Support both structured JSON logging (production) and human-readable text logging
      (development) based on environment configuration.
    - Provide a single setup function called once at application startup.

Workflow:
    1. Application startup calls `setup_logging()`.
    2. All existing `logging` handlers are removed and replaced with a Loguru interceptor.
    3. Loguru is configured with console + optional file sinks based on settings.
    4. All modules use `from loguru import logger` directly — no further setup needed.
"""

import logging
import sys
from pathlib import Path

from loguru import logger

from config.settings import settings


class _InterceptHandler(logging.Handler):
    """Intercepts standard library logging and redirects to Loguru.

    This handler bridges Python's built-in `logging` module with Loguru,
    ensuring that third-party libraries (LangChain, FastAPI, ChromaDB, etc.)
    that use standard logging are captured and formatted consistently.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Converts a standard LogRecord into a Loguru log entry.

        Args:
            record: The standard library LogRecord to intercept and forward.
        """
        # Map standard logging level to Loguru level name
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk up the call stack to find the true caller outside this handler
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _build_json_formatter() -> str:
    """Returns a Loguru format string that produces structured JSON-like output.

    Returns:
        A Loguru-compatible format string for structured log output.
    """
    return (
        "{{"
        '"time": "{time:YYYY-MM-DDTHH:mm:ss.SSS}Z", '
        '"level": "{level}", '
        '"module": "{module}", '
        '"function": "{function}", '
        '"line": {line}, '
        '"message": "{message}"'
        "}}"
    )


def _build_text_formatter() -> str:
    """Returns a human-readable Loguru format string for development.

    Returns:
        A Loguru-compatible format string for console-friendly log output.
    """
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )


def _ensure_log_directory(log_file_path: str) -> None:
    """Creates the log file's parent directory if it does not exist.

    Args:
        log_file_path: Absolute or relative path to the intended log file.
    """
    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)


def _intercept_standard_logging() -> None:
    """Replaces all standard logging handlers with the Loguru interceptor.

    This ensures consistent log formatting across the entire application,
    including third-party libraries that use Python's built-in logging.
    """
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Explicitly intercept common noisy third-party loggers
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "langchain",
        "chromadb",
        "neo4j",
        "httpx",
        "httpcore",
    ):
        third_party_logger = logging.getLogger(logger_name)
        third_party_logger.handlers = [_InterceptHandler()]
        third_party_logger.propagate = False


def setup_logging() -> None:
    """Initialises Loguru with sinks and format based on application settings.

    This function must be called exactly once at application startup, before
    any other module emits log messages. Subsequent calls are safe but redundant.

    The function:
        - Removes Loguru's default sink.
        - Adds a console sink formatted for the current environment.
        - Optionally adds a rotating file sink if LOG_FILE is configured.
        - Intercepts Python standard library logging.

    Raises:
        OSError: If the log file directory cannot be created due to permissions.
    """
    log_level: str = settings.logging.log_level.upper()
    use_json: bool = settings.logging.log_format.lower() == "json"

    # Remove Loguru's default stderr sink before adding custom sinks
    logger.remove()

    console_format = _build_json_formatter() if use_json else _build_text_formatter()

    # Console sink — always active
    logger.add(
        sys.stdout,
        level=log_level,
        format=console_format,
        colorize=not use_json,   # colours only make sense for text format
        backtrace=True,          # full traceback on exceptions
        diagnose=True,           # variable values in tracebacks (disable in prod)
        enqueue=False,           # synchronous in dev; set True for async workers
    )

    # File sink — only if a log file path is configured
    if settings.logging.log_file:
        _ensure_log_directory(settings.logging.log_file)

        logger.add(
            settings.logging.log_file,
            level=log_level,
            format=_build_json_formatter(),   # always JSON in files for parsing
            rotation="10 MB",                 # rotate when file reaches 10 MB
            retention="30 days",              # keep logs for 30 days
            compression="zip",                # compress rotated files
            backtrace=True,
            diagnose=False,                   # omit variable values in file logs (security)
            enqueue=True,                     # async writes to avoid blocking I/O
            encoding="utf-8",
        )

    # Route all standard library logging through Loguru
    _intercept_standard_logging()

    logger.info(
        "Logging initialised | level={} | format={} | file={}",
        log_level,
        settings.logging.log_format,
        settings.logging.log_file or "disabled",
    )