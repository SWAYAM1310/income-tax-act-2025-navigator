"""Structured JSON logging. Every agent step and pipeline stage logs one event via get_logger()."""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure(level: int = logging.INFO, json: bool = True) -> None:
    global _configured
    if _configured:
        return
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    _configured = True


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    configure()
    return structlog.get_logger(name)
