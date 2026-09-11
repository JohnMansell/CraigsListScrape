import os
import sys
from pathlib import Path

from loguru import logger

LOG_FILENAME = "craigslist.log"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> Path:
    """Send logs to stderr and to a file rotated at midnight, keeping 10 files.

    Replaces any handlers from an earlier call. The directory is `log_dir`, else
    `$CRAIGSLIST_LOGDIR`, else `logs/` in the repo. Returns the log file path.
    """
    if log_dir is None:
        log_dir = Path(os.environ.get("CRAIGSLIST_LOGDIR", DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILENAME
    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add(log_file, level=level, rotation="00:00", retention=10)
    return log_file
