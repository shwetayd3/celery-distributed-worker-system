from flask import Flask, jsonify, request
from celery.result import AsyncResult

from app.celery_app import celery
from app.tasks.compute_tasks import sum_of_squares, fibonacci, matrix_multiply
from app.tasks.io_tasks import simulate_file_processing, fetch_url_mock, batch_process_files
from app.tasks.sample_tasks import add, countdown_task, chain_demo
from config.app_config import Config

app = Flask(__name__)
app.config.from_object(Config)

# ── Health ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "broker": Config.REDIS_URL})


# ── Task submission ──────────────────────────────────────────────────────────

@app.route("/tasks/compute/sum-of-squares", methods=["POST"])
def submit_sum_of_squares():
    data = request.get_json(force=True)
    n = data.get("n", 10000)
    if not isinstance(n, int) or n <= 0:
        return jsonify({"error": "n must be a positive integer"}), 400
    task = sum_of_squares.apply_async(args=[n], queue="high_priority")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "high_priority"}), 202


@app.route("/tasks/compute/fibonacci", methods=["POST"])
def submit_fibonacci():
    data = request.get_json(force=True)
    n = data.get("n", 10)
    if not isinstance(n, int) or n < 0:
        return jsonify({"error": "n must be a non-negative integer"}), 400
    task = fibonacci.apply_async(args=[n], queue="high_priority")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "high_priority"}), 202


@app.route("/tasks/compute/matrix-multiply", methods=["POST"])
def submit_matrix_multiply():
    data = request.get_json(force=True)
    size = data.get("size", 100)
    task = matrix_multiply.apply_async(args=[size], queue="high_priority")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "high_priority"}), 202


@app.route("/tasks/io/file-process", methods=["POST"])
def submit_file_process():
    data = request.get_json(force=True)
    filename = data.get("filename", "sample.txt")
    task = simulate_file_processing.apply_async(args=[filename], queue="io_tasks")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "io_tasks"}), 202


@app.route("/tasks/io/fetch-url", methods=["POST"])
def submit_fetch_url():
    data = request.get_json(force=True)
    url = data.get("url", "https://example.com")
    task = fetch_url_mock.apply_async(args=[url], queue="io_tasks")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "io_tasks"}), 202


@app.route("/tasks/io/batch-process", methods=["POST"])
def submit_batch_process():
    data = request.get_json(force=True)
    files = data.get("files", [])
    if not files or not isinstance(files, list):
        return jsonify({"error": "files must be a non-empty list"}), 400
    task = batch_process_files.apply_async(args=[files], queue="io_tasks")
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "io_tasks"}), 202


@app.route("/tasks/sample/add", methods=["POST"])
def submit_add():
    data = request.get_json(force=True)
    x = data.get("x", 0)
    y = data.get("y", 0)
    task = add.apply_async(args=[x, y])
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "default"}), 202


@app.route("/tasks/sample/countdown", methods=["POST"])
def submit_countdown():
    data = request.get_json(force=True)
    seconds = data.get("seconds", 5)
    task = countdown_task.apply_async(args=[seconds])
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "default"}), 202


@app.route("/tasks/sample/chain", methods=["POST"])
def submit_chain():
    data = request.get_json(force=True)
    n = data.get("n", 5)
    task = chain_demo.apply_async(args=[n])
    return jsonify({"task_id": task.id, "status": "PENDING", "queue": "default"}), 202


# ── Task status & result ─────────────────────────────────────────────────────

@app.route("/tasks/<task_id>/status", methods=["GET"])
def get_task_status(task_id):
    result = AsyncResult(task_id, app=celery)
    response = {
        "task_id": task_id,
        "status": result.status,
    }
    if result.successful():
        response["result"] = result.result
    elif result.failed():
        response["error"] = str(result.result)
        response["traceback"] = result.traceback
    elif result.status == "PROGRESS":
        response["meta"] = result.info
    return jsonify(response)


@app.route("/tasks/<task_id>/revoke", methods=["DELETE"])
def revoke_task(task_id):
    celery.control.revoke(task_id, terminate=True)
    return jsonify({"task_id": task_id, "status": "REVOKED"})


# ── Worker info ──────────────────────────────────────────────────────────────

@app.route("/workers", methods=["GET"])
def list_workers():
    inspect = celery.control.inspect(timeout=2.0)
    active = inspect.active() or {}
    stats = inspect.stats() or {}
    workers = []
    for worker_name, tasks in active.items():
        workers.append({
            "name": worker_name,
            "active_tasks": len(tasks),
            "tasks": tasks,
            "stats": stats.get(worker_name, {}),
        })
    return jsonify({"workers": workers, "total": len(workers)})


@app.route("/queues", methods=["GET"])
def list_queues():
    inspect = celery.control.inspect(timeout=2.0)
    reserved = inspect.reserved() or {}
    queues = {}
    for worker, tasks in reserved.items():
        for task in tasks:
            q = task.get("delivery_info", {}).get("routing_key", "unknown")
            queues[q] = queues.get(q, 0) + 1
    return jsonify({"queues": queues})


if __name__ == "__main__":
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=5000)
