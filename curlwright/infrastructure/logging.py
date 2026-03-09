"""Logging configuration for infrastructure and application layers."""

import logging
import sys

from curlwright.runtime import ensure_supported_python

ensure_supported_python()


def setup_logger(name: str, level: int | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if level is None:
        level = logging.INFO
    logger.setLevel(level)
    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(level)
        return logger

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger
