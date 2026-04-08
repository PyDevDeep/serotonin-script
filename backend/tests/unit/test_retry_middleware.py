from unittest.mock import MagicMock, patch

import pytest
from taskiq import TaskiqMessage

from backend.workers.middlewares.retry import RetryTrackerMiddleware


def make_message(retry_count=0, task_id="task-1", task_name="my_task") -> TaskiqMessage:
    msg = MagicMock(spec=TaskiqMessage)
    msg.labels = {"retry_count": retry_count}
    msg.task_id = task_id
    msg.task_name = task_name
    return msg


@pytest.fixture
def middleware():
    return RetryTrackerMiddleware()


# --- no retry: no warning ---


def test_pre_execute_no_retry_no_warning(middleware):
    msg = make_message(retry_count=0)
    with patch.object(middleware, "pre_execute", wraps=middleware.pre_execute) as _:
        with patch("backend.workers.middlewares.retry.logger") as mock_logger:
            result = middleware.pre_execute(msg)
    mock_logger.warning.assert_not_called()
    assert result is msg


# --- first retry: warning logged ---


def test_pre_execute_first_retry_logs_warning(middleware):
    msg = make_message(retry_count=1, task_id="abc", task_name="gen_content")
    with patch("backend.workers.middlewares.retry.logger") as mock_logger:
        result = middleware.pre_execute(msg)
    mock_logger.warning.assert_called_once_with(
        "task_retry_attempt",
        task_id="abc",
        task_name="gen_content",
        attempt=1,
    )
    assert result is msg


# --- multiple retries: warning each time ---


def test_pre_execute_multiple_retries_logs_warning(middleware):
    for count in [2, 5, 10]:
        msg = make_message(retry_count=count)
        with patch("backend.workers.middlewares.retry.logger") as mock_logger:
            middleware.pre_execute(msg)
        mock_logger.warning.assert_called_once()


# --- string retry count (taskiq labels are strings) ---


def test_pre_execute_string_retry_count(middleware):
    msg = make_message()
    msg.labels = {"retry_count": "3"}
    with patch("backend.workers.middlewares.retry.logger") as mock_logger:
        result = middleware.pre_execute(msg)
    mock_logger.warning.assert_called_once()
    assert result is msg


def test_pre_execute_string_zero_retry_no_warning(middleware):
    msg = make_message()
    msg.labels = {"retry_count": "0"}
    with patch("backend.workers.middlewares.retry.logger") as mock_logger:
        result = middleware.pre_execute(msg)
    mock_logger.warning.assert_not_called()
    assert result is msg


# --- missing label key: defaults to 0, no warning ---


def test_pre_execute_missing_retry_label(middleware):
    msg = make_message()
    msg.labels = {}
    with patch("backend.workers.middlewares.retry.logger") as mock_logger:
        result = middleware.pre_execute(msg)
    mock_logger.warning.assert_not_called()
    assert result is msg


# --- returns same message object (not a copy) ---


def test_pre_execute_returns_same_message_object(middleware):
    msg = make_message(retry_count=2)
    with patch("backend.workers.middlewares.retry.logger"):
        result = middleware.pre_execute(msg)
    assert result is msg
