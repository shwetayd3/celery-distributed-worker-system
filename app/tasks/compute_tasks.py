import time
import random
import logging

from app.celery_app import celery

logger = logging.getLogger(__name__)

@celery.task(
    bind=True,
    name="compute.sum_of_squares",
    max_retries=3,
    default_retry_delay=5,
    queue="high_priority",
)
def sum_of_squares(self, n: int) -> int:
    """
    Compute the sum of squares from 0 to n-1.
    Simulates CPU work; retries on transient errors.
    """
    logger.info(f"[sum_of_squares] Starting with n={n}")
    try:
        # Report progress back to the result backend
        self.update_state(state="PROGRESS", meta={"current": 0, "total": n})
        result = 0
        chunk = max(n // 10, 1)
        for i in range(n):
            result += i * i
            if i % chunk == 0:
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i, "total": n, "partial": result},
                )
        logger.info(f"[sum_of_squares] Done. Result={result}")
        return result
    except Exception as exc:
        logger.error(f"[sum_of_squares] Failed: {exc}")
        raise self.retry(exc=exc)


@celery.task(
    bind=True,
    name="compute.fibonacci",
    max_retries=3,
    default_retry_delay=5,
    queue="high_priority",
)
def fibonacci(self, n: int) -> int:
    """
    Compute the nth Fibonacci number iteratively.
    Uses memoization-style iteration to avoid stack overflow on large n.
    """
    logger.info(f"[fibonacci] Computing F({n})")
    try:
        if n < 0:
            raise ValueError("n must be non-negative")
        if n == 0:
            return 0
        if n == 1:
            return 1
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        logger.info(f"[fibonacci] F({n}) = {b}")
        return b
    except Exception as exc:
        logger.error(f"[fibonacci] Failed: {exc}")
        raise self.retry(exc=exc)


@celery.task(
    bind=True,
    name="compute.matrix_multiply",
    max_retries=2,
    default_retry_delay=10,
    queue="high_priority",
    time_limit=120,
)
def matrix_multiply(self, size: int) -> dict:
    """
    Multiply two randomly-generated size x size matrices.
    Pure Python (no numpy) to demonstrate CPU load.
    Returns the sum of all result elements and elapsed time.
    """
    logger.info(f"[matrix_multiply] size={size}x{size}")
    try:
        start = time.time()

        def make_matrix(s):
            return [[random.uniform(0, 1) for _ in range(s)] for _ in range(s)]

        A = make_matrix(size)
        B = make_matrix(size)

        # Naive O(n^3) multiplication
        C = [[0.0] * size for _ in range(size)]
        for i in range(size):
            for k in range(size):
                for j in range(size):
                    C[i][j] += A[i][k] * B[k][j]

        total = sum(C[i][j] for i in range(size) for j in range(size))
        elapsed = round(time.time() - start, 4)
        logger.info(f"[matrix_multiply] Done in {elapsed}s")
        return {"size": size, "result_sum": round(total, 4), "elapsed_seconds": elapsed}
    except Exception as exc:
        logger.error(f"[matrix_multiply] Failed: {exc}")
        raise self.retry(exc=exc)
