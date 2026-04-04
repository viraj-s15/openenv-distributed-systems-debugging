from pydantic import ValidationError

from models import Action, Observation, SystemMetrics


def test_system_metrics_rejects_success_rate_above_one() -> None:
    try:
        SystemMetrics(
            gateway_success_rate=1.2,
            gateway_p99_latency_ms=20,
            queue_depth=0,
            worker_restart_count=0,
            consumer_stall_count=0,
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for success rate > 1.0")


def test_observation_roundtrip() -> None:
    original = Observation(
        command_output="ok",
        metrics=SystemMetrics(
            gateway_success_rate=0.7,
            gateway_p99_latency_ms=123,
            queue_depth=3,
            worker_restart_count=1,
            consumer_stall_count=2,
        ),
        process_status={"gateway": "running pid=42"},
    )

    restored = Observation.model_validate_json(original.model_dump_json())
    assert restored == original


def test_action_rejects_empty_command() -> None:
    try:
        Action(command="   ")
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for empty command")
