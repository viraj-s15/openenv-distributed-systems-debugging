from typing import Any

from openenv.core import EnvClient
from openenv.core.client_types import StepResult as ClientStepResult
from openenv.core.env_server.types import State

from .models import Action, Observation, SystemMetrics


class DistributedSystemsDebugEnv(EnvClient[Action, Observation]):
    """Client wrapper around the environment HTTP API."""

    def _step_payload(self, action: Action) -> dict[str, Any]:
        return action.model_dump()

    def _parse_result(self, payload: dict[str, Any]) -> ClientStepResult[Observation]:
        observation_payload = payload.get("observation") or {}
        metrics_payload = observation_payload.get("metrics") or {}

        observation = Observation(
            command_output=str(observation_payload.get("command_output") or ""),
            metrics=SystemMetrics(
                gateway_success_rate=float(
                    metrics_payload.get("gateway_success_rate", 0.0)
                ),
                gateway_p99_latency_ms=float(
                    metrics_payload.get("gateway_p99_latency_ms", 0.0)
                ),
                queue_depth=int(metrics_payload.get("queue_depth", 0)),
                worker_restart_count=int(
                    metrics_payload.get("worker_restart_count", 0)
                ),
                consumer_stall_count=int(
                    metrics_payload.get("consumer_stall_count", 0)
                ),
            ),
            process_status={
                str(key): str(value)
                for key, value in dict(
                    observation_payload.get("process_status") or {}
                ).items()
            },
        )

        reward = payload.get("reward")
        return ClientStepResult(
            observation=observation,
            reward=float(reward) if reward is not None else None,
            done=bool(payload.get("done", False)),
        )

    def _parse_state(self, payload: dict[str, Any]) -> State:
        return State(
            episode_id=payload.get("task"),
            step_count=int(payload.get("step_count", 0)),
        )
