from __future__ import annotations

import logging
import sys


def setup_logging() -> None:
    """Centralized logging config.

    IMPORTANT: handlers must never log raw personal data (phone numbers,
    full names, message text). Log IDs and event types only.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Keep noisy third-party loggers quieter.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
