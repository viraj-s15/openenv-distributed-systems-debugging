import os

from server.constants import TaskName
from inference import (
    _attempt_history_block,
    _episode_score,
    _format_end_line,
    _parse_tasks,
    _single_line,
    _task_symptom_block,
    build_prompt,
    extract_command,
    extract_reasoning,
)
from server.models import Observation, SystemMetrics


def test_extract_command_rejects_non_json_code_fence() -> None:
    raw = "```bash\nredis-cli LLEN job_queue\n```"
    assert extract_command(raw) is None


def test_extract_command_returns_none_when_empty() -> None:
    assert extract_command("   ") is None


def test_extract_command_reads_json_payload() -> None:
    raw = '{"command":"redis-cli LLEN job_queue"}'
    assert extract_command(raw) == "redis-cli LLEN job_queue"


def test_extract_command_reads_fenced_json_payload() -> None:
    raw = '```json\n{"command":"ps -ef"}\n```'
    assert extract_command(raw) == "ps -ef"


def test_extract_command_reads_json_embedded_in_text() -> None:
    raw = 'Use this command: {"command":"redis-cli LLEN job_queue"} thanks.'
    assert extract_command(raw) == "redis-cli LLEN job_queue"


def test_extract_command_reads_json_after_reasoning_preamble() -> None:
    raw = (
        "I'll start by checking process state.\n"
        '{"command":"ps aux","reasoning":"list processes"}'
    )
    assert extract_command(raw) == "ps aux"
    assert extract_reasoning(raw) == "list processes"


def test_extract_command_prefers_first_json_object_with_command() -> None:
    raw = '{"meta":"skip"} then {"command":"ls -la","reasoning":"explore"}'
    assert extract_command(raw) == "ls -la"


def test_extract_reasoning_when_present() -> None:
    raw = '{"command":"redis-cli LLEN job_queue","reasoning":"check queue depth first"}'
    assert extract_command(raw) == "redis-cli LLEN job_queue"
    assert extract_reasoning(raw) == "check queue depth first"


def test_extract_command_requires_command_even_with_reasoning() -> None:
    raw = '{"reasoning":"i should inspect logs"}'
    assert extract_command(raw) is None
    assert extract_reasoning(raw) is None


def test_single_line_removes_newlines() -> None:
    assert _single_line("echo a\necho b") == "echo a echo b"


def test_task_symptom_block_is_non_empty() -> None:
    block = _task_symptom_block(TaskName.ROUTE_PARTITION)
    assert "connectivity path issue" in block
    assert "route-partition" not in block


def test_task_symptom_block_includes_new_tasks() -> None:
    registry_block = _task_symptom_block(TaskName.REGISTRY_CORRUPTION)
    runaway_block = _task_symptom_block(TaskName.JOB_GENERATOR_RUNAWAY)

    assert "registry" in registry_block.lower()
    assert "queue" in runaway_block.lower()
    assert "job-generator-runaway" not in runaway_block


def test_attempt_history_block_renders_all_attempts() -> None:
    attempts = [
        {
            "step": 1,
            "command": "redis-cli LLEN job_queue",
            "reasoning": "check backlog",
            "reward": 0.12,
            "error": None,
        },
        {
            "step": 2,
            "command": "curl -s localhost:3000/health",
            "reasoning": None,
            "reward": 0.08,
            "error": "timeout",
        },
    ]
    block = _attempt_history_block(attempts)
    assert "step 1: command=redis-cli LLEN job_queue" in block
    assert "step 2: command=curl -s localhost:3000/health" in block
    assert "reasoning=check backlog" in block
    assert "error=timeout" in block
    assert "reward=" not in block


def test_build_prompt_contains_symptoms_and_history() -> None:
    obs = Observation(
        command_output="service checks show partial failures",
        metrics=SystemMetrics(
            gateway_success_rate=0.32,
            gateway_p99_latency_ms=1500.0,
            queue_depth=412,
            worker_restart_count=3,
            consumer_stall_count=2,
        ),
        process_status={"gateway": "running", "worker": "running"},
    )
    prompt = build_prompt(
        obs=obs,
        step_num=3,
        task_name=TaskName.BACKPRESSURE_CASCADE,
        attempt_history=[
            {
                "step": 1,
                "command": "redis-cli LLEN job_queue",
                "reasoning": "measure backlog",
                "reward": 0.10,
                "error": None,
            }
        ],
    )
    assert "TASK SYMPTOMS:" in prompt
    assert "PREVIOUS ATTEMPTS:" in prompt
    assert "step 1: command=redis-cli LLEN job_queue" in prompt
    assert "LATEST COMMAND OUTPUT:" in prompt
    assert "reward=" not in prompt


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
        assert _parse_tasks() == [
            TaskName.ROUTE_PARTITION,
            TaskName.BACKPRESSURE_CASCADE,
        ]

        os.environ["TASKS_CSV"] = "registry-corruption,job-generator-runaway"
        assert _parse_tasks() == [
            TaskName.REGISTRY_CORRUPTION,
            TaskName.JOB_GENERATOR_RUNAWAY,
        ]
    finally:
        if previous is None:
            os.environ.pop("TASKS_CSV", None)
        else:
            os.environ["TASKS_CSV"] = previous



def test_episode_score_clamps_terminal_reward_to_unit_interval() -> None:
    assert _episode_score([]) == 0.01
    assert _episode_score([0.2, 0.8]) == 0.8
    assert _episode_score([1.2]) == 0.99
    assert _episode_score([-0.1]) == 0.01


def test_end_log_line_includes_score_and_reward_list() -> None:
    line = _format_end_line(success=True, steps=3, score=0.987, rewards=[0.0, 0.125, 1.0])
    assert line == (
        "[END]   success=true steps=3 score=0.99 rewards=0.00,0.12,1.00"
    )