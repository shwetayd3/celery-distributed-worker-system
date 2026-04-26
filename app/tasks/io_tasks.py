"""
io_tasks.py
I/O-bound tasks routed to the io_tasks queue.
These simulate disk reads, network calls, and batch file operations.
"""
import time
import random
import logging
import hashlib

from app.celery_app import celery
from app.utils.helpers import format_bytes, retry_with_backoff

logger = logging.getLogger(__name__)

@celery.task(
    bind=True,
    name="io.simulate_file_processing",
    max_retries=5,
    default_retry_delay=3,
    queue="io_tasks",
)
def simulate_file_processing(self, filename: str) -> dict:
    """
    Simulates reading and processing a file:
    - Fake I/O delay
    - Computes a mock checksum
    - Returns file metadata
    """
    logger.info(f"[file_processing] Processing: {filename}")
    try:
        start = time.time()

        # Simulate variable I/O latency
        io_delay = random.uniform(0.5, 2.5)
        time.sleep(io_delay)

        # Simulate random transient I/O failure (10% chance)
        if random.random() < 0.10:
            raise IOError(f"Transient read error on {filename}")

        # Fake checksum
        checksum = hashlib.md5(filename.encode()).hexdigest()
        fake_size = random.randint(1024, 10 * 1024 * 1024)

        result = {
            "filename": filename,
            "checksum": checksum,
            "size": format_bytes(fake_size),
            "io_delay_seconds": round(io_delay, 3),
            "elapsed_seconds": round(time.time() - start, 3),
            "status": "processed",
        }
        logger.info(f"[file_processing] Done: {result}")
        return result

    except IOError as exc:
        logger.warning(f"[file_processing] IOError, retrying: {exc}")
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.error(f"[file_processing] Unexpected error: {exc}")
        raise


@celery.task(
    bind=True,
    name="io.fetch_url_mock",
    max_retries=4,
    default_retry_delay=5,
    queue="io_tasks",
    soft_time_limit=30,
)
def fetch_url_mock(self, url: str) -> dict:
    """
    Simulates fetching a URL:
    - Random latency to mimic network RTT
    - Occasional timeouts that trigger retries
    - Returns mock response metadata
    """
    logger.info(f"[fetch_url] Fetching: {url}")
    try:
        start = time.time()
        latency = random.uniform(0.2, 3.0)
        time.sleep(latency)

        # Simulate occasional network timeout (15% chance)
        if random.random() < 0.15:
            raise TimeoutError(f"Request to {url} timed out")

        status_code = random.choice([200, 200, 200, 301, 404])
        result = {
            "url": url,
            "status_code": status_code,
            "latency_seconds": round(latency, 3),
            "elapsed_seconds": round(time.time() - start, 3),
            "content_length": random.randint(500, 50000),
            "success": status_code < 400,
        }
        logger.info(f"[fetch_url] Done: {status_code} in {latency:.2f}s")
        return result

    except TimeoutError as exc:
        logger.warning(f"[fetch_url] Timeout, retrying: {exc}")
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.error(f"[fetch_url] Unexpected error: {exc}")
        raise


@celery.task(
    bind=True,
    name="io.batch_process_files",
    max_retries=2,
    default_retry_delay=10,
    queue="io_tasks",
    time_limit=300,
)
def batch_process_files(self, filenames: list) -> dict:
    """
    Processes a batch of files sequentially.
    Reports progress via update_state for each file.
    Returns a summary with per-file results.
    """
    logger.info(f"[batch_process] Starting batch of {len(filenames)} files")
    results = []
    failed = []

    for idx, filename in enumerate(filenames):
        self.update_state(
            state="PROGRESS",
            meta={
                "current": idx,
                "total": len(filenames),
                "current_file": filename,
            },
        )
        try:
            io_delay = random.uniform(0.3, 1.5)
            time.sleep(io_delay)
            checksum = hashlib.sha256(filename.encode()).hexdigest()[:16]
            results.append({
                "filename": filename,
                "checksum": checksum,
                "status": "ok",
                "elapsed": round(io_delay, 3),
            })
        except Exception as exc:
            logger.error(f"[batch_process] Failed on {filename}: {exc}")
            failed.append({"filename": filename, "error": str(exc)})

    summary = {
        "total": len(filenames),
        "succeeded": len(results),
        "failed": len(failed),
        "results": results,
        "errors": failed,
    }
    logger.info(f"[batch_process] Done: {summary['succeeded']}/{summary['total']} succeeded")
    return summary
