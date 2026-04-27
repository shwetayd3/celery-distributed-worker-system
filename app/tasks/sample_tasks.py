"""
sample_tasks.py
Demo tasks for testing and onboarding.
Includes basic tasks, chaining, grouping, error simulation.
"""

import time
import random
import logging

from celery import chain, group, chord

from app.celery_app import celery

logger = logging.getLogger(__name__)

@celery.task(
    bind=True,
    name="sample.add",
    max_retries=3,
    queue="default",
)
def add(self, x: float, y: float) -> float:
    """Add two numbers. Simplest possible Celery task."""
    logger.info(f"[add] {x} + {y}")
    return x + y


@celery.task(
    bind=True,
    name="sample.multiply",
    queue="default",
)
def multiply(self, x: float, y: float) -> float:
    """Multiply two numbers."""
    logger.info(f"[multiply] {x} * {y}")
    return x * y


@celery.task(
    bind=True,
    name="sample.countdown_task",
    max_retries=1,
    queue="default",
)
def countdown_task(self, seconds: int) -> dict:
    """
    Counts down from `seconds` to 0, reporting progress each second.
    Good for testing Flower's real-time progress tracking.
    """
    logger.info(f"[countdown] Starting {seconds}s countdown")
    for i in range(seconds, 0, -1):
        self.update_state(
            state="PROGRESS",
            meta={"remaining": i, "total": seconds},
        )
        time.sleep(1)
    logger.info("[countdown] Done")
    return {"status": "complete", "seconds": seconds}


@celery.task(
    bind=True,
    name="sample.chain_demo",
    queue="default",
)
def chain_demo(self, n: int) -> dict:
    """
    Demonstrates Celery chains:
    add(n, n) -> multiply(result, 2) -> add(result, 10)
    """
    logger.info(f"[chain_demo] Running chain with n={n}")
    pipeline = chain(
        add.si(n, n),
        multiply.s(2),
        add.s(10),
    )
    result = pipeline.apply()
    return {
        "input": n,
        "steps": f"add({n},{n}) -> multiply(2) -> add(10)",
        "result": result.get(),
    }


@celery.task(
    bind=True,
    name="sample.group_demo",
    queue="default",
)
def group_demo(self, numbers: list) -> dict:
    """
    Demonstrates Celery groups: runs add(x, x) for each number in parallel.
    """
    logger.info(f"[group_demo] Running group for {numbers}")
    job = group(add.s(n, n) for n in numbers)
    result = job.apply_async()
    results = result.get(timeout=30)
    return {
        "inputs": numbers,
        "results": results,
        "total": sum(results),
    }


@celery.task(
    bind=True,
    name="sample.failing_task",
    max_retries=3,
    default_retry_delay=2,
    queue="default",
)
def failing_task(self, fail_probability: float = 0.8) -> str:
    """
    Intentionally fails with given probability.
    Useful for testing retry logic and Flower failure monitoring.
    """
    logger.info(f"[failing_task] Running with fail_probability={fail_probability}")
    if random.random() < fail_probability:
        exc = RuntimeError("Simulated task failure for testing")
        logger.warning(f"[failing_task] Failing on attempt {self.request.retries + 1}")
        raise self.retry(exc=exc)
    logger.info("[failing_task] Succeeded after retries")
    return "Task succeeded eventually"


@celery.task(
    bind=True,
    name="sample.long_running_task",
    queue="default",
    time_limit=600,
    soft_time_limit=500,
)
def long_running_task(self, duration: int = 30) -> dict:
    """
    Runs for `duration` seconds, reporting progress every 5 seconds.
    Tests soft/hard time limits and long-running job monitoring in Flower.
    """
    logger.info(f"[long_running] Starting {duration}s task")
    start = time.time()
    elapsed = 0
    while elapsed < duration:
        time.sleep(min(5, duration - elapsed))
        elapsed = round(time.time() - start, 1)
        self.update_state(
            state="PROGRESS",
            meta={"elapsed": elapsed, "total": duration, "pct": round(elapsed / duration * 100, 1)},
        )
    return {"duration": duration, "actual_elapsed": round(time.time() - start, 2)}
