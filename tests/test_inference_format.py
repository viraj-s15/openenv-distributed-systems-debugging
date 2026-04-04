import os

from constants import TaskName
from inference import _parse_tasks, _single_line, extract_command


def test_extract_command_removes_code_fence() -> None:
    raw = "```bash\nredis-cli LLEN job_queue\n```"
    assert extract_command(raw) == "redis-cli LLEN job_queue"


def test_extract_command_falls_back_when_empty() -> None:
    assert extract_command("   ") == "ls /tmp"


def test_single_line_removes_newlines() -> None:
    assert _single_line("echo a\necho b") == "echo a echo b"


def test_parse_tasks_default_and_override() -> None:
    previous = os.getenv("TASKS_CSV")
    try:
        os.environ.pop("TASKS_CSV", None)
        default_tasks = _parse_tasks()
        assert default_tasks == [
            TaskName.CASCADING_TIMEOUT,
            TaskName.BYZANTINE_QUEUE_FAULT,
            TaskName.DISTRIBUTED_LOCK_STARVATION,
        ]

        os.environ["TASKS_CSV"] = "route-partition,backpressure-cascade"
        assert _parse_tasks() == [TaskName.ROUTE_PARTITION, TaskName.BACKPRESSURE_CASCADE]
    finally:
        if previous is None:
            os.environ.pop("TASKS_CSV", None)
        else:
            os.environ["TASKS_CSV"] = previous
