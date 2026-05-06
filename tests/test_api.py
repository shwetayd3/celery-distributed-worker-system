"""
test_api.py
Integration tests for the Flask REST API.
Uses a mocked Celery backend so no Redis is needed.
Run with: pytest tests/test_api.py -v
"""
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["DEBUG"] = False
    with app.test_client() as c:
        yield c


def make_mock_task(task_id="abc-123", status="PENDING"):
    mock = MagicMock()
    mock.id = task_id
    mock.status = status
    mock.successful.return_value = status == "SUCCESS"
    mock.failed.return_value = status == "FAILURE"
    mock.result = 42 if status == "SUCCESS" else None
    mock.traceback = None
    mock.info = {}
    return mock


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert "broker" in data


# ── Task Submission ───────────────────────────────────────────────────────────

class TestComputeEndpoints:
    @patch("app.api.sum_of_squares")
    def test_submit_sum_of_squares(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t1")
        res = client.post("/tasks/compute/sum-of-squares", json={"n": 1000})
        assert res.status_code == 202
        data = res.get_json()
        assert data["task_id"] == "t1"
        assert data["queue"] == "high_priority"

    @patch("app.api.sum_of_squares")
    def test_submit_invalid_n(self, mock_task, client):
        res = client.post("/tasks/compute/sum-of-squares", json={"n": -5})
        assert res.status_code == 400

    @patch("app.api.fibonacci")
    def test_submit_fibonacci(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t2")
        res = client.post("/tasks/compute/fibonacci", json={"n": 20})
        assert res.status_code == 202
        assert res.get_json()["task_id"] == "t2"

    @patch("app.api.matrix_multiply")
    def test_submit_matrix_multiply(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t3")
        res = client.post("/tasks/compute/matrix-multiply", json={"size": 50})
        assert res.status_code == 202


class TestIOEndpoints:
    @patch("app.api.simulate_file_processing")
    def test_submit_file_process(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t4")
        res = client.post("/tasks/io/file-process", json={"filename": "data.csv"})
        assert res.status_code == 202
        assert res.get_json()["queue"] == "io_tasks"

    @patch("app.api.fetch_url_mock")
    def test_submit_fetch_url(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t5")
        res = client.post("/tasks/io/fetch-url", json={"url": "https://example.com"})
        assert res.status_code == 202

    @patch("app.api.batch_process_files")
    def test_submit_batch_process(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t6")
        res = client.post("/tasks/io/batch-process", json={"files": ["a.txt", "b.txt"]})
        assert res.status_code == 202

    @patch("app.api.batch_process_files")
    def test_batch_empty_files_rejected(self, mock_task, client):
        res = client.post("/tasks/io/batch-process", json={"files": []})
        assert res.status_code == 400


class TestSampleEndpoints:
    @patch("app.api.add")
    def test_submit_add(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t7")
        res = client.post("/tasks/sample/add", json={"x": 3, "y": 4})
        assert res.status_code == 202

    @patch("app.api.countdown_task")
    def test_submit_countdown(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task("t8")
        res = client.post("/tasks/sample/countdown", json={"seconds": 5})
        assert res.status_code == 202


# ── Task Status ───────────────────────────────────────────────────────────────

class TestTaskStatus:
    @patch("app.api.AsyncResult")
    def test_pending_status(self, mock_async, client):
        mock_async.return_value = make_mock_task("abc", "PENDING")
        res = client.get("/tasks/abc/status")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "PENDING"
        assert "result" not in data

    @patch("app.api.AsyncResult")
    def test_success_status(self, mock_async, client):
        mock_result = make_mock_task("abc", "SUCCESS")
        mock_result.result = 12345
        mock_async.return_value = mock_result
        res = client.get("/tasks/abc/status")
        data = res.get_json()
        assert data["status"] == "SUCCESS"
        assert data["result"] == 12345

    @patch("app.api.AsyncResult")
    def test_failure_status(self, mock_async, client):
        mock_result = make_mock_task("abc", "FAILURE")
        mock_result.result = RuntimeError("boom")
        mock_result.traceback = "Traceback..."
        mock_async.return_value = mock_result
        res = client.get("/tasks/abc/status")
        data = res.get_json()
        assert data["status"] == "FAILURE"
        assert "error" in data


# ── Revoke ────────────────────────────────────────────────────────────────────

class TestRevoke:
    @patch("app.api.celery")
    def test_revoke_task(self, mock_celery, client):
        mock_celery.control.revoke = MagicMock()
        res = client.delete("/tasks/abc-123/revoke")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "REVOKED"
        mock_celery.control.revoke.assert_called_once_with("abc-123", terminate=True)


# ── Workers ───────────────────────────────────────────────────────────────────

class TestWorkerEndpoints:
    @patch("app.api.celery")
    def test_list_workers(self, mock_celery, client):
        mock_inspect = MagicMock()
        mock_inspect.active.return_value = {
            "worker-default@host": [{"name": "sample.add", "id": "xyz"}]
        }
        mock_inspect.stats.return_value = {"worker-default@host": {"pool": "prefork"}}
        mock_celery.control.inspect.return_value = mock_inspect
        res = client.get("/workers")
        assert res.status_code == 200
        data = res.get_json()
        assert data["total"] == 1
        assert data["workers"][0]["name"] == "worker-default@host"

    @patch("app.api.celery")
    def test_list_queues(self, mock_celery, client):
        mock_inspect = MagicMock()
        mock_inspect.reserved.return_value = {
            "worker@host": [
                {"delivery_info": {"routing_key": "default"}},
                {"delivery_info": {"routing_key": "high_priority"}},
            ]
        }
        mock_celery.control.inspect.return_value = mock_inspect
        res = client.get("/queues")
        assert res.status_code == 200
        data = res.get_json()
        assert "default" in data["queues"]
