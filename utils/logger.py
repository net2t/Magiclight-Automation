"""
MagicLight v2.0 — Logging
Provides system-level logger (logs/system.log) and per-job logger (logs/job_{ID}.log).
"""

import logging
import sys
from pathlib import Path
from utils.config import LOGS_DIR


def _make_handler(path: Path, level=logging.DEBUG) -> logging.FileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    return h


def get_system_logger(name: str = "magiclight") -> logging.Logger:
    """Returns the shared system logger that writes to logs/system.log."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger                         # already initialised

    logger.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s",
                                      datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    # File handler
    logger.addHandler(_make_handler(LOGS_DIR / "system.log"))
    return logger


def get_job_logger(job_id: str) -> logging.Logger:
    """Returns a per-job logger that writes to logs/job_{ID}.log."""
    name = f"job.{job_id}"
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.addHandler(_make_handler(LOGS_DIR / f"job_{job_id}.log"))
    logger.propagate = True          # also appears in system logger
    return logger
