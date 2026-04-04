import json
from pathlib import Path

from server.constants import DEFAULT_CONFIGS
from server.env import DistributedDebugEnv


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_restore_defaults_adds_job_generator_config(tmp_path: Path) -> None:
    mesh_root = tmp_path / "mesh"
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=mesh_root)

    env._restore_defaults()

    payload = json.loads(
        (mesh_root / "worker" / "job_generator_config.json").read_text()
    )
    assert payload == DEFAULT_CONFIGS["job_generator"]


def test_registry_auth_matches_default_detects_corruption(tmp_path: Path) -> None:
    mesh_root = tmp_path / "mesh"
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=mesh_root)
    env._restore_defaults()

    assert env._is_registry_auth_default() is True

    _write_json(
        mesh_root / "registry.json",
        {
            "services": {
                "auth": {"host": "invalid-host", "port": 3001, "protocol": "http"},
                "redis": {"host": "localhost", "port": 6379, "protocol": "tcp"},
                "worker": {"host": "localhost", "port": None, "protocol": "internal"},
            }
        },
    )

    assert env._is_registry_auth_default() is False


def test_job_generator_rate_resolved_uses_config(tmp_path: Path) -> None:
    mesh_root = tmp_path / "mesh"
    env = DistributedDebugEnv(project_root=tmp_path, mesh_root=mesh_root)
    env._restore_defaults()

    assert env._job_generator_interval_ms() == 333
    assert env._is_job_generator_rate_resolved() is True

    _write_json(mesh_root / "worker" / "job_generator_config.json", {"interval_ms": 10})

    assert env._job_generator_interval_ms() == 10
    assert env._is_job_generator_rate_resolved() is False
