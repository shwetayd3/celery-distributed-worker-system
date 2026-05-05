"""
submit_sample_tasks.py
Submits a variety of tasks across all queues to test the system end-to-end.
Run with: python scripts/submit_sample_tasks.py
"""
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tasks.compute_tasks import sum_of_squares, fibonacci, matrix_multiply
from app.tasks.io_tasks import simulate_file_processing, fetch_url_mock, batch_process_files
from app.tasks.sample_tasks import add, countdown_task, failing_task, group_demo


def separator(title: str):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print("=" * 50)


def submit_and_poll(task_result, label: str, timeout: int = 30):
    """Submit a task and poll until complete or timeout."""
    print(f"\n[{label}] Task ID: {task_result.id}")
    start = time.time()
    while time.time() - start < timeout:
        status = task_result.status
        if status in ("SUCCESS", "FAILURE"):
            break
        if status == "PROGRESS":
            print(f"  [{label}] Progress: {task_result.info}")
        time.sleep(1)

    if task_result.successful():
        print(f"  [{label}] SUCCESS → {task_result.result}")
    elif task_result.failed():
        print(f"  [{label}] FAILURE → {task_result.result}")
    else:
        print(f"  [{label}] Status: {task_result.status} (timed out polling)")


def main():
    print("\n🚀 Submitting sample tasks to all queues...\n")

    # ── Default queue ──────────────────────────────────────────────────────
    separator("Default Queue — sample tasks")

    t1 = add.apply_async(args=[42, 58])
    submit_and_poll(t1, "add(42, 58)")

    t2 = group_demo.apply_async(args=[[1, 2, 3, 4, 5]])
    submit_and_poll(t2, "group_demo([1..5])", timeout=20)

    # ── High-priority queue ────────────────────────────────────────────────
    separator("High Priority Queue — compute tasks")

    t3 = fibonacci.apply_async(args=[30], queue="high_priority")
    submit_and_poll(t3, "fibonacci(30)")

    t4 = sum_of_squares.apply_async(args=[500_000], queue="high_priority")
    submit_and_poll(t4, "sum_of_squares(500000)", timeout=30)

    t5 = matrix_multiply.apply_async(args=[50], queue="high_priority")
    submit_and_poll(t5, "matrix_multiply(50x50)", timeout=60)

    # ── IO queue ──────────────────────────────────────────────────────────
    separator("IO Queue — I/O-bound tasks")

    t6 = simulate_file_processing.apply_async(args=["report_2024.csv"], queue="io_tasks")
    submit_and_poll(t6, "file_processing(report_2024.csv)", timeout=15)

    t7 = fetch_url_mock.apply_async(args=["https://api.example.com/data"], queue="io_tasks")
    submit_and_poll(t7, "fetch_url(api.example.com)", timeout=15)

    t8 = batch_process_files.apply_async(
        args=[["file1.txt", "file2.log", "file3.csv", "file4.json"]],
        queue="io_tasks",
    )
    submit_and_poll(t8, "batch_process(4 files)", timeout=30)

    # ── Retry / failure demonstration ─────────────────────────────────────
    separator("Retry Demo — failing_task (will retry 3x)")

    t9 = failing_task.apply_async(args=[0.5])  # 50% fail probability
    submit_and_poll(t9, "failing_task(p=0.5)", timeout=30)

    separator("All tasks submitted and polled")
    print("\n✅ Done. Check Flower at http://localhost:5555 for full history.\n")


if __name__ == "__main__":
    main()
