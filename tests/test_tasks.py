"""
test_tasks.py
Unit tests for all Celery tasks using an in-memory broker.
Run with: pytest tests/ -v
"""
import pytest
from unittest.mock import patch, MagicMock

from celery.contrib.pytest import celery_app, celery_worker  # noqa: F401


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def celery_config():
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True,   # Run tasks synchronously in tests
        "task_eager_propagates": True,
    }


# ── Compute Tasks ─────────────────────────────────────────────────────────────

class TestSumOfSquares:
    def test_basic(self):
        from app.tasks.compute_tasks import sum_of_squares
        result = sum_of_squares.apply(args=[5]).get()
        assert result == 0 + 1 + 4 + 9 + 16  # 0^2 + 1^2 + 2^2 + 3^2 + 4^2

    def test_zero(self):
        from app.tasks.compute_tasks import sum_of_squares
        result = sum_of_squares.apply(args=[0]).get()
        assert result == 0

    def test_large_n(self):
        from app.tasks.compute_tasks import sum_of_squares
        n = 1000
        expected = sum(i * i for i in range(n))
        result = sum_of_squares.apply(args=[n]).get()
        assert result == expected


class TestFibonacci:
    @pytest.mark.parametrize("n,expected", [
        (0, 0),
        (1, 1),
        (2, 1),
        (5, 5),
        (10, 55),
        (20, 6765),
    ])
    def test_known_values(self, n, expected):
        from app.tasks.compute_tasks import fibonacci
        result = fibonacci.apply(args=[n]).get()
        assert result == expected

    def test_negative_raises(self):
        from app.tasks.compute_tasks import fibonacci
        with pytest.raises(Exception):
            fibonacci.apply(args=[-1]).get()


class TestMatrixMultiply:
    def test_returns_dict(self):
        from app.tasks.compute_tasks import matrix_multiply
        result = matrix_multiply.apply(args=[5]).get()
        assert isinstance(result, dict)
        assert "size" in result
        assert "result_sum" in result
        assert "elapsed_seconds" in result
        assert result["size"] == 5

    def test_elapsed_positive(self):
        from app.tasks.compute_tasks import matrix_multiply
        result = matrix_multiply.apply(args=[3]).get()
        assert result["elapsed_seconds"] >= 0


# ── IO Tasks ──────────────────────────────────────────────────────────────────

class TestSimulateFileProcessing:
    @patch("app.tasks.io_tasks.random.uniform", return_value=0.01)
    @patch("app.tasks.io_tasks.random.random", return_value=0.5)   # no failure
    @patch("app.tasks.io_tasks.time.sleep")
    def test_returns_metadata(self, mock_sleep, mock_random, mock_uniform):
        from app.tasks.io_tasks import simulate_file_processing
        result = simulate_file_processing.apply(args=["test.txt"]).get()
        assert result["filename"] == "test.txt"
        assert result["status"] == "processed"
        assert "checksum" in result
        assert "size" in result

    @patch("app.tasks.io_tasks.random.uniform", return_value=0.01)
    @patch("app.tasks.io_tasks.random.random", return_value=0.05)  # triggers IOError
    @patch("app.tasks.io_tasks.time.sleep")
    def test_retries_on_io_error(self, mock_sleep, mock_random, mock_uniform):
        from app.tasks.io_tasks import simulate_file_processing
        # With task_always_eager=True and max_retries, this should raise after retries
        with pytest.raises(Exception):
            simulate_file_processing.apply(args=["bad_file.txt"]).get()


class TestBatchProcessFiles:
    @patch("app.tasks.io_tasks.random.uniform", return_value=0.01)
    @patch("app.tasks.io_tasks.time.sleep")
    def test_batch_summary(self, mock_sleep, mock_uniform):
        from app.tasks.io_tasks import batch_process_files
        files = ["a.txt", "b.txt", "c.txt"]
        result = batch_process_files.apply(args=[files]).get()
        assert result["total"] == 3
        assert result["succeeded"] + result["failed"] == 3
        assert "results" in result
        assert "errors" in result


# ── Sample Tasks ──────────────────────────────────────────────────────────────

class TestAdd:
    @pytest.mark.parametrize("x,y,expected", [
        (1, 2, 3),
        (-1, 1, 0),
        (0, 0, 0),
        (1.5, 2.5, 4.0),
    ])
    def test_add(self, x, y, expected):
        from app.tasks.sample_tasks import add
        result = add.apply(args=[x, y]).get()
        assert result == expected


class TestGroupDemo:
    def test_group_sums(self):
        from app.tasks.sample_tasks import group_demo
        result = group_demo.apply(args=[[1, 2, 3]]).get()
        assert result["inputs"] == [1, 2, 3]
        assert result["results"] == [2, 4, 6]
        assert result["total"] == 12


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_format_bytes(self):
        from app.utils.helpers import format_bytes
        assert "B" in format_bytes(512)
        assert "KB" in format_bytes(2048)
        assert "MB" in format_bytes(2 * 1024 * 1024)

    def test_chunk_list(self):
        from app.utils.helpers import chunk_list
        result = chunk_list([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2], [3, 4], [5]]

    def test_safe_divide(self):
        from app.utils.helpers import safe_divide
        assert safe_divide(10, 2) == 5.0
        assert safe_divide(10, 0) == 0.0
        assert safe_divide(10, 0, default=-1) == -1

    def test_retry_with_backoff_success(self):
        from app.utils.helpers import retry_with_backoff
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ValueError("not yet")
            return "ok"

        result = retry_with_backoff(flaky, max_retries=3, base_delay=0)
        assert result == "ok"
        assert call_count["n"] == 3

    def test_retry_with_backoff_exhausted(self):
        from app.utils.helpers import retry_with_backoff
        with pytest.raises(RuntimeError):
            retry_with_backoff(
                lambda: (_ for _ in ()).throw(RuntimeError("always fails")),
                max_retries=2,
                base_delay=0,
            )
