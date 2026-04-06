from fastapi.testclient import TestClient

from server import api
from server.constants import TaskName
from server.models import Observation, SystemMetrics


class _FakeEnv:
    def __init__(self) -> None:
        self.reset_calls: list[TaskName] = []

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def reset(self, task_name: TaskName) -> Observation:
        self.reset_calls.append(task_name)
        return Observation(
            command_output="ready",
            metrics=SystemMetrics(
                gateway_success_rate=0.0,
                gateway_p99_latency_ms=0.0,
                queue_depth=0,
                worker_restart_count=0,
                consumer_stall_count=0,
            ),
            process_status={"gateway": "running"},
        )


def test_reset_defaults_to_cascading_timeout_when_task_missing(monkeypatch) -> None:
    holder: dict[str, _FakeEnv] = {}

    def fake_env_factory() -> _FakeEnv:
        env = _FakeEnv()
        holder["env"] = env
        return env

    monkeypatch.setattr(api, "DistributedDebugEnv", fake_env_factory)

    with TestClient(api.app) as client:
        response = client.post("/reset", json={})

    assert response.status_code == 200
    assert holder["env"].reset_calls == [TaskName.CASCADING_TIMEOUT]


def test_reset_rejects_unknown_explicit_task(monkeypatch) -> None:
    holder: dict[str, _FakeEnv] = {}

    def fake_env_factory() -> _FakeEnv:
        env = _FakeEnv()
        holder["env"] = env
        return env

    monkeypatch.setattr(api, "DistributedDebugEnv", fake_env_factory)

    with TestClient(api.app) as client:
        response = client.post("/reset", params={"task_name": "not-a-task"}, json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown task: not-a-task"
    assert holder["env"].reset_calls == []
