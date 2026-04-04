import os
from typing import Any

import httpx
from constants import DEFAULT_BASELINE_TASK_ENUMS, TaskName
from models import Action, Observation, StepResult

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
BENCHMARK = "distributed-systems-debug-env"
MAX_STEPS = int(os.getenv("MAX_STEPS", "10"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

SYSTEM_PROMPT = """You have bash access to a distributed job processing pipeline that is experiencing a failure.
Use bash commands to investigate the system, identify the root cause, and fix it.
Standard Unix tools are available: ps, ls, cat, grep, tail, curl, jq, redis-cli, kill, sed.
Issue ONE bash command per step. Respond with ONLY the command, no explanation."""


class DistributedDebugEnvClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=45.0)

    def close(self) -> None:
        self._client.close()

    def reset(self, task_name: str) -> Observation:
        response = self._client.post("/reset", params={"task_name": task_name})
        response.raise_for_status()
        return Observation.model_validate(response.json())

    def step(self, action: Action) -> StepResult:
        response = self._client.post("/step", json=action.model_dump())
        response.raise_for_status()
        return StepResult.model_validate(response.json())


def _parse_tasks() -> list[TaskName]:
    csv = os.getenv("TASKS_CSV", "").strip()
    if not csv:
        return list(DEFAULT_BASELINE_TASK_ENUMS)

    tasks: list[TaskName] = []
    for value in csv.split(","):
        task_str = value.strip()
        if not task_str:
            continue
        tasks.append(TaskName.parse(task_str))

    return tasks


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _single_line(text: str) -> str:
    return " ".join(text.replace("\t", " ").splitlines()).strip()


def extract_command(llm_response: str) -> str:
    response = llm_response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        if len(lines) > 2:
            response = "\n".join(lines[1:-1]).strip()

    first_line = response.split("\n")[0].strip()
    return first_line or "ls /tmp"


def build_prompt(obs: Observation, step_num: int) -> str:
    return (
        f"Step {step_num}. Current system state:\n\n"
        "METRICS:\n"
        f"- Gateway success rate: {obs.metrics.gateway_success_rate:.1%}\n"
        f"- Gateway P99 latency: {obs.metrics.gateway_p99_latency_ms:.0f}ms\n"
        f"- Queue depth: {obs.metrics.queue_depth}\n"
        f"- Worker restarts: {obs.metrics.worker_restart_count}\n"
        f"- Consumer stall count: {obs.metrics.consumer_stall_count}\n\n"
        "SERVICE STATUS:\n"
        f"{obs.process_status}\n\n"
        "LAST COMMAND OUTPUT:\n"
        f"{obs.command_output[:2000]}\n\n"
        "Issue a single bash command to investigate or fix the problem.\n"
        "Respond with ONLY the bash command, nothing else."
    )


def _run_episode(client: Any, env: DistributedDebugEnvClient, task_name: TaskName) -> None:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    rewards: list[float] = []

    done = False
    step = 0
    last_error: str | None = None

    print(f"[START] task={task_name.value} env={BENCHMARK} model={MODEL_NAME}", flush=True)

    try:
        obs = env.reset(task_name=task_name.value)
        while not done and step < MAX_STEPS:
            next_step = step + 1
            user_prompt = build_prompt(obs, next_step)
            messages.append({"role": "user", "content": user_prompt})

            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=128,
            )

            raw_response = completion.choices[0].message.content or ""
            command = extract_command(raw_response)
            messages.append({"role": "assistant", "content": command})

            result = env.step(Action(command=command))
            obs = result.observation
            rewards.append(result.reward)
            done = result.done

            error_value = result.info.get("error")
            last_error = None if error_value in (None, "", "None") else str(error_value)
            error_field = "null" if last_error is None else _single_line(last_error)

            print(
                f"[STEP]  step={next_step} action={_single_line(command)} "
                f"reward={result.reward:.2f} done={_bool(done)} error={error_field}",
                flush=True,
            )
            step = next_step

    except Exception as exc:
        last_error = str(exc)
    finally:
        success = bool(done and rewards and rewards[-1] >= 0.95)
        rewards_csv = ",".join(f"{reward:.2f}" for reward in rewards)
        print(
            f"[END]   success={_bool(success)} steps={step} rewards={rewards_csv}",
            flush=True,
        )


def main() -> None:
    if not API_KEY:
        raise RuntimeError("HF_TOKEN (or API_KEY) must be set")

    tasks = _parse_tasks()

    from openai import OpenAI

    client = OpenAI(
        api_key=API_KEY,
        base_url=API_BASE_URL,
        timeout=30.0,
        max_retries=2,
    )
    env = DistributedDebugEnvClient(base_url=ENV_URL)

    try:
        for task_name in tasks:
            _run_episode(client, env, task_name)
    finally:
        env.close()


if __name__ == "__main__":
    main()
