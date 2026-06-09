from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "decomplexer"

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_CONSOLE_FORMAT = "%(levelname)s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"

def setup_logging(*, verbosity: int = 0, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setLevel(_console_level(verbosity))
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(file_handler)
        logger.debug("File log opened at %s", log_file)

    return logger

def _console_level(verbosity: int) -> int:
    return logging.WARNING - 10 * min(max(verbosity, 0), 2)
