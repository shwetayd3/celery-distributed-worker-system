"""
helpers.py
Shared utility functions used across tasks and API.
"""
import time
import logging
import functools
from typing import Callable, Any

logger = logging.getLogger(__name__)


def format_bytes(size: int) -> str:
    """Convert a byte count to a human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """
    Standalone retry helper (not Celery-specific).
    Useful for retrying third-party calls inside a task.

    Args:
        func:           Callable to attempt.
        max_retries:    Maximum number of attempts.
        base_delay:     Initial delay in seconds.
        backoff_factor: Multiplied by base_delay on each retry.
        exceptions:     Tuple of exception types to catch and retry on.

    Returns:
        The return value of func() on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    delay = base_delay
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except exceptions as exc:
            last_exc = exc
            logger.warning(
                f"[retry_with_backoff] Attempt {attempt}/{max_retries} failed: {exc}. "
                f"Retrying in {delay:.1f}s..."
            )
            if attempt < max_retries:
                time.sleep(delay)
                delay *= backoff_factor
    raise last_exc


def timed(func: Callable) -> Callable:
    """Decorator that logs the execution time of a function."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = round(time.time() - start, 4)
        logger.info(f"[timed] {func.__name__} completed in {elapsed}s")
        return result
    return wrapper


def chunk_list(lst: list, size: int) -> list:
    """Split a list into chunks of a given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide two numbers, returning default if denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator
