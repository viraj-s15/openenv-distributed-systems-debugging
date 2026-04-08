from pathlib import Path

from server.env import DistributedDebugEnv
from server.models import Observation, SystemMetrics


def _observation(*, success: float, depth: int, restarts: int, stalls: int) -> Observation:
    return Observation(
        command_output="ok",
        metrics=SystemMetrics(
            gateway_success_rate=success,
            gateway_p99_latency_ms=100.0,
            queue_depth=depth,
            worker_restart_count=restarts,
            consumer_stall_count=stalls,
        ),
        process_status={"gateway": "running"},
    )


def test_compute_reward_no_command_uses_open_interval_floor(tmp_path: Path) -> None:
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=tmp_path / "mesh")
    current = _observation(success=0.5, depth=10, restarts=0, stalls=0)

    reward = env._compute_reward(
        command="__NO_COMMAND_PROVIDED__",
        current=current,
        previous=current,
        grader_score=0.5,
        previous_grader_score=0.5,
        command_error="no_command_provided",
    )

    assert reward == 0.01


def test_compute_reward_terminal_success_uses_open_interval_ceiling(tmp_path: Path) -> None:
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=tmp_path / "mesh")
    current = _observation(success=0.99, depth=0, restarts=0, stalls=0)

    reward = env._compute_reward(
        command="redis-cli LLEN job_queue",
        current=current,
        previous=current,
        grader_score=0.95,
        previous_grader_score=0.9,
        command_error=None,
    )

    assert reward == 0.99


def test_compute_reward_final_clamp_stays_open_interval(tmp_path: Path) -> None:
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=tmp_path / "mesh")
    previous = _observation(success=0.3, depth=40, restarts=5, stalls=3)
    current = _observation(success=0.9, depth=5, restarts=1, stalls=0)

    reward = env._compute_reward(
        command="redis-cli set debug_key value",
        current=current,
        previous=previous,
        grader_score=0.94,
        previous_grader_score=0.2,
        command_error=None,
    )

    assert reward == 0.99


def test_compute_reward_penalty_clamps_to_open_interval_floor(tmp_path: Path) -> None:
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=tmp_path / "mesh")
    previous = _observation(success=0.9, depth=2, restarts=0, stalls=0)
    current = _observation(success=0.1, depth=50, restarts=5, stalls=5)
    env.last_exit_code = 1

    reward = env._compute_reward(
        command="echo",
        current=current,
        previous=previous,
        grader_score=0.01,
        previous_grader_score=0.9,
        command_error="blocked_command",
    )

    assert reward == 0.01
